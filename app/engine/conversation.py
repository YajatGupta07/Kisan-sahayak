"""Inbound message handling: text, voice, photo, location -> case updates -> planner.advance()."""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import clock, config
from app.engine import consent, faq, planner
from app.engine.record import decide, say, set_fact
from app.models.case import Case, Evidence, Message
from app.models.enums import CaseState, FactSource, Intent, TERMINAL_STATES
from app.nlu import extract_loss, hindi_dates, intent as intent_mod
from app.responses import hi
from app.tools import photo_evidence
from app.voice import stt

S = CaseState
PRE_REPORT = {S.NEW, S.INTAKE, S.DEADLINE_CONFIRM, S.GATHER, S.REPORT_CONSENT, S.CROP_MISMATCH}


def phone_hash(phone: str) -> str:
    return hashlib.sha256(phone.encode()).hexdigest()


def mask_phone(phone: str) -> str:
    digits = "".join(ch for ch in phone if ch.isdigit())
    return "XXXXXX" + digits[-4:] if len(digits) >= 4 else "XXXX"


def get_or_create_case(db: Session, phone: str, channel: str = "simulator") -> Case:
    h = phone_hash(phone)
    case = db.scalars(select(Case).where(Case.phone_hash == h).order_by(Case.id.desc()).limit(1)).first()
    if case and S(case.state) not in TERMINAL_STATES:
        return case
    now = clock.now()
    case = Case(phone_hash=h, phone_masked=mask_phone(phone), channel=channel, state=S.NEW.value, flags={},
                created_at=now, updated_at=now)
    db.add(case)
    db.flush()
    return case


def _diff(db: Session, case: Case, ev: extract_loss.LossEvent, msg_time: datetime) -> dict:
    """Values in the message that differ from what the case holds now."""
    out: dict = {}
    if ev.event_type and ev.event_type != case.event_type:
        out["event_type"] = ev.event_type
    if ev.crop and ev.crop != case.crop_reported:
        out["crop_reported"] = ev.crop
    if ev.area_ha is not None and (case.area_ha is None or abs(ev.area_ha - case.area_ha) > 0.005):
        out["area_ha"] = ev.area_ha
    if ev.event_time_text:
        r = hindi_dates.resolve(ev.event_time_text, msg_time)
        if r.at and r.at != case.event_at:
            out["event_at"] = r.at
            out["_time_assumed"] = not r.has_time_of_day
        elif r.at is None and case.event_at is None:
            out["_time_unresolved"] = ev.event_time_text
    if ev.khasra and ev.khasra != case.flag("farmer_khasra"):
        out["farmer_khasra"] = ev.khasra
    if ev.village and ev.village != case.village:
        out["village"] = ev.village
    if ev.harvested and not case.flag("harvested"):
        out["harvested"] = True
    if ev.widespread and not case.flag("widespread"):
        out["widespread"] = True
    return out


def _apply(db: Session, case: Case, diff: dict, ev: extract_loss.LossEvent, msg: Message) -> None:
    ref = f"msg:{msg.id}"
    for k in ("event_type", "crop_reported", "area_ha", "village"):
        if k in diff:
            note = ev.area_text if k == "area_ha" else None
            set_fact(db, case, k, diff[k], FactSource.FARMER, evidence_ref=ref, note=note)
    if "event_at" in diff:
        set_fact(db, case, "event_at", diff["event_at"], FactSource.FARMER, evidence_ref=ref,
                 note=f"from: {ev.event_time_text}")
        set_fact(db, case, "event_time_text", ev.event_time_text, FactSource.FARMER, evidence_ref=ref)
        case.set_flag("time_assumed", diff.get("_time_assumed", False))
        case.set_flag("event_time_unresolved", None)
    if "_time_unresolved" in diff:
        case.set_flag("event_time_unresolved", diff["_time_unresolved"])
    if "farmer_khasra" in diff:
        case.set_flag("farmer_khasra", diff["farmer_khasra"])
        case.set_flag("land_checked", False)
        set_fact(db, case, "farmer_khasra", diff["farmer_khasra"], FactSource.FARMER, evidence_ref=ref)
    for k in ("harvested", "widespread"):
        if k in diff:
            case.set_flag(k, True)
    # identifiers are kept as flags (masked in the fact log)
    if ev.receipt_no:
        case.set_flag("receipt_no", ev.receipt_no)
        set_fact(db, case, "identifier_given", f"receipt {ev.receipt_no}", FactSource.FARMER, evidence_ref=ref)
    if ev.loan_account:
        case.set_flag("loan_account", ev.loan_account)
        set_fact(db, case, "identifier_given", f"loan a/c XXXX{ev.loan_account[-4:]}", FactSource.FARMER,
                 evidence_ref=ref)
    if ev.otp:
        case.set_flag("otp", ev.otp)
    if ev.no_photos:
        case.set_flag("no_photos", True)
    # claim route follows the (possibly corrected) event
    if case.event_type:
        ctype = extract_loss.claim_type_for(case.event_type, case.flag("harvested"))
        if ctype != case.claim_type:
            set_fact(db, case, "claim_type", ctype, FactSource.AGENT_ESTIMATE,
                     note="PMFBY route from event type" + (" + harvested" if case.flag("harvested") else ""))
            decide(db, case, f"claim_type:{ctype}", f"event={case.event_type}, harvested={case.flag('harvested')}")
    # a changed event/time/crop before filing means the deadline read-back must be redone
    if S(case.state) in (S.GATHER, S.REPORT_CONSENT) and ({"event_at", "event_type"} & set(diff)):
        case.state = S.INTAKE.value
        case.reference_no = None
        decide(db, case, "reconfirm_deadline", "event details changed before filing; deadline read-back again")
    elif S(case.state) == S.REPORT_CONSENT:
        case.state = S.GATHER.value


def handle_text(db: Session, case: Case, msg: Message, text: str) -> None:
    awaiting = case.flag("awaiting")
    case.set_flag("awaiting", None)  # answered; the next ask sets it again
    ev, cost = extract_loss.extract(text, awaiting=awaiting)
    case.cost_inr += cost
    diff = _diff(db, case, ev, msg.at)
    has_new = any(not k.startswith("_") for k in diff)
    pending = consent.pending(db, case)
    it, cost = intent_mod.classify(text, has_new_info=has_new, after_readback=pending is not None)
    case.cost_inr += cost
    msg.meta = {**(msg.meta or {}), "intent": it.value, "extracted": ev.fields()}

    if pending is not None:
        if it == Intent.QUESTION and not has_new:
            say(db, case, faq.answer(db, case, text) + "\n\n(ऊपर वाली बात के लिए *हाँ* या *नहीं* बताइए।)")
            return
        if it == Intent.INFO and has_new:
            it = Intent.CORRECTION
        res = consent.on_reply(db, case, msg, it)
        if res == "executed":
            return  # executor advanced the case
        if res == "declined":
            kind = pending.kind
            if kind in ("CONFIRM_DEADLINE", "REPORT_LOSS"):
                case.state = S.INTAKE.value if kind == "CONFIRM_DEADLINE" else S.GATHER.value
                say(db, case, hi.ASK_CORRECTION, ask="correction")
                return
            # grievance / RTI / correction declined: nothing is filed; say so and leave the case readable
            from_state = pending.payload.get("from_state", case.state)
            case.state = S.BLOCKED.value if from_state in (S.CROP_MISMATCH.value, S.DIAGNOSE.value) else from_state
            if case.state == S.BLOCKED.value:
                case.outcome = "BLOCKED"
                if not case.blocker:
                    case.blocker = "Crop recorded in policy differs from sown crop"
                    case.next_step = "Visit enrolling bank/CSC to correct crop"
            say(db, case, "ठीक है, मैंने आपके नाम से कुछ भी जमा नहीं किया।"
                + (f" आगे का रास्ता: {case.next_step}" if case.next_step else ""))
            return
        if res == "correction":
            case.state = pending.payload.get("from_state", case.state)
            if case.state == S.DEADLINE_CONFIRM.value:
                case.state = S.INTAKE.value
            _apply(db, case, diff, ev, msg)
            planner.advance(db, case)
            return
        say(db, case, "कृपया ऊपर पढ़ी गई जानकारी के लिए साफ *हाँ* या *नहीं* बताइए।", ask="confirm")
        return

    if it == Intent.QUESTION and not has_new and not (ev.receipt_no or ev.loan_account or ev.otp):
        say(db, case, faq.answer(db, case, text))
        return
    if case.flag("weather_reconfirm_open"):
        set_fact(db, case, "farmer_restatement", text[:300], FactSource.FARMER, evidence_ref=f"msg:{msg.id}",
                 note="farmer's account after weather record disagreed; both versions kept")
        case.set_flag("weather_reconfirm_open", False)
    if awaiting == "correction" and not has_new:
        say(db, case, "कृपया बताइए कि क्या गलत है — जैसे सही तारीख, फसल या रकबा।", ask="correction")
        return
    _apply(db, case, diff, ev, msg)
    if S(case.state) == S.NEW:
        case.state = S.INTAKE.value
        if not (case.event_type or case.crop_reported):
            say(db, case, hi.GREETING, ask="event_type")
            return
    planner.advance(db, case)


def handle_photo(db: Session, case: Case, msg: Message, path: str, *, capture_method: str,
                 forwarded: Optional[bool] = None, lat: Optional[float] = None, lon: Optional[float] = None,
                 captured_at: Optional[datetime] = None) -> Evidence:
    now = clock.now()
    meta = photo_evidence.read_meta(path)
    seen = db.scalars(select(Evidence).where(Evidence.sha256 == meta.sha256, Evidence.case_id != case.id)).first()
    if lat is None and capture_method != "capture_page":  # recent live location from the same chat
        loc = db.scalars(select(Evidence).where(Evidence.case_id == case.id, Evidence.kind == "location",
                                                Evidence.received_at >= now - timedelta(minutes=30))
                         .order_by(Evidence.id.desc())).first()
        if loc:
            lat, lon = loc.lat, loc.lon
            if captured_at is None and meta.captured_at is None:
                captured_at = now  # arrival time, corroborated by live location in the same session
    if capture_method == "capture_page" and captured_at is None:
        captured_at = now  # server time at upload
    ok, problems, resolved = photo_evidence.validate(
        meta, event_at=case.event_at, now=now, village=case.village, capture_method=capture_method,
        captured_at=captured_at, lat=lat, lon=lon, forwarded=forwarded, seen_elsewhere=seen is not None)
    crop, dmg, cost = (None, None, 0.0)
    if meta.readable:
        crop, dmg, cost = photo_evidence.vision_check(path)
        case.cost_inr += cost
    e = Evidence(case_id=case.id, kind="photo", sha256=meta.sha256, received_at=now,
                 captured_at=resolved["captured_at"], lat=resolved["lat"], lon=resolved["lon"],
                 capture_method=capture_method, exif_ok=meta.exif_ok, forwarded=forwarded, crop_detected=crop,
                 damage_detected=dmg, valid=ok, problems=problems, path=path)
    db.add(e)
    db.flush()
    if crop:
        case.set_flag("photo_crop", crop)
    n = planner.valid_photo_count(db, case)
    if ok:
        decide(db, case, "photo_accepted", f"photo {e.id}: method={capture_method}, time+location ok", {"valid": n})
        say(db, case, f"फोटो मिल गई ✅ ({n}/{config.MIN_VALID_PHOTOS})" + (f" — फोटो में {hi.crop(crop)} दिख रही है।" if crop else ""))
    else:
        reasons = "; ".join(photo_evidence.problem_hi(p) for p in problems)
        decide(db, case, "photo_rejected", f"photo {e.id}: {problems}")
        fix = []
        if {"no_capture_time", "no_location"} & set(problems):
            fix.append(f"खेत में खड़े होकर इस लिंक से फोटो लें: {planner.capture_link(case)} — या फोटो Document की तरह भेजकर "
                       "लाइव लोकेशन शेयर करें")
        say(db, case, f"यह फोटो सबूत के तौर पर नहीं ली जा सकी: {reasons}।" + ("\n" + "\n".join(fix) if fix else "")
            + f"\n(अब तक सही फोटो: {n}/{config.MIN_VALID_PHOTOS})", ask="photos")
    return e


def handle_location(db: Session, case: Case, lat: float, lon: float) -> None:
    now = clock.now()
    db.add(Evidence(case_id=case.id, kind="location", received_at=now, captured_at=now, lat=lat, lon=lon, valid=True))
    db.flush()
    # photos that only lacked location in the last 30 min can now be re-checked
    recent = db.scalars(select(Evidence).where(Evidence.case_id == case.id, Evidence.kind == "photo",
                                               Evidence.valid.is_(False),
                                               Evidence.received_at >= now - timedelta(minutes=30))).all()
    fixed = 0
    for e in recent:
        if set(e.problems or []) <= {"no_location", "no_capture_time"}:
            e.lat, e.lon = lat, lon
            e.captured_at = e.captured_at or e.received_at
            meta = photo_evidence.PhotoMeta(sha256=e.sha256, readable=True)
            ok, problems, _ = photo_evidence.validate(meta, event_at=case.event_at, now=now, village=case.village,
                                                      capture_method=e.capture_method, captured_at=e.captured_at,
                                                      lat=lat, lon=lon, forwarded=e.forwarded)
            e.valid, e.problems = ok, problems
            fixed += ok
    n = planner.valid_photo_count(db, case)
    say(db, case, "लोकेशन मिल गई 📍" + (f" — {fixed} फोटो अब मान्य हैं ({n}/{config.MIN_VALID_PHOTOS})" if fixed else ""))


def handle_inbound(db: Session, phone: str, *, text: Optional[str] = None, photo_path: Optional[str] = None,
                   as_document: bool = False, via_capture_page: bool = False, forwarded: Optional[bool] = None,
                   lat: Optional[float] = None, lon: Optional[float] = None, audio_path: Optional[str] = None,
                   audio_seconds: float = 0.0, channel: str = "simulator", case: Optional[Case] = None) -> Case:
    case = case or get_or_create_case(db, phone, channel)
    msg = Message(case_id=case.id, direction="in", at=clock.now(), text=text,
                  media_kind="photo" if photo_path else ("voice" if audio_path else None),
                  media_path=photo_path or audio_path, meta={})
    db.add(msg)
    db.flush()
    if audio_path:
        transcript = stt.transcribe(audio_path)
        case.cost_inr += audio_seconds / 60 * config.STT_INR_PER_MIN
        if not transcript:
            say(db, case, hi.VOICE_FAILED, ask=case.flag("awaiting"))
            return case
        msg.meta = {"transcript": transcript}
        text = transcript
    if photo_path:
        method = "capture_page" if via_capture_page else ("document" if as_document else "photo")
        handle_photo(db, case, msg, photo_path, capture_method=method, forwarded=forwarded, lat=lat, lon=lon)
        if not text:
            planner.advance(db, case)
            return case
    elif lat is not None and lon is not None and not text:
        handle_location(db, case, lat, lon)
        planner.advance(db, case)
        return case
    if text:
        handle_text(db, case, msg, text)
    case.updated_at = clock.now()
    return case
