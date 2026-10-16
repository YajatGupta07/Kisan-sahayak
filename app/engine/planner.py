"""Planner: picks the next step from the case state, logs a Decision with the reason for each choice.

Guards (which actions are allowed) live in the state handlers; anything consequential goes through
consent.propose(). Executors are registered with @consent.executor and are never called directly.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import clock, config
from app.engine import consent, record
from app.engine.record import decide, say, set_fact
from app.models.case import Action, Case, ChannelAttempt, Evidence, ScheduledCheck
from app.models.enums import ActionKind, CaseState, CheckKind, ClaimType, FactSource, Outcome
from app.responses import hi
from app.tools import (claim_status, diagnosis, documents, land_records, policy_lookup, weather,
                       yield_engine)
from app.tools.reporting import channels

S = CaseState


# ------------------------------------------------------------------ helpers
def capture_link(case: Case) -> str:
    return f"{config.PUBLIC_BASE_URL}/capture/{case.token}"


def _hours_left(case: Case, now: datetime) -> Optional[float]:
    return None if not case.deadline_at else (case.deadline_at - now).total_seconds() / 3600


def _policy(case: Case) -> dict:
    return case.flag("policy") or {}


def _grievances(case: Case) -> dict[str, datetime]:
    return {k: datetime.fromisoformat(v) for k, v in (case.flag("grievances") or {}).items()}


def valid_photo_count(db: Session, case: Case) -> int:
    return db.scalar(select(func.count()).select_from(Evidence).where(
        Evidence.case_id == case.id, Evidence.kind == "photo", Evidence.valid.is_(True))) or 0


def _close(db: Session, case: Case, state: CaseState, outcome: Outcome) -> None:
    case.state = state.value
    case.outcome = outcome.value
    case.closed_at = clock.now()
    record.cancel_checks(db, case)


# ------------------------------------------------------------------ main loop
def advance(db: Session, case: Case, max_steps: int = 25) -> None:
    for _ in range(max_steps):
        if consent.pending(db, case):
            return
        fn = _STEPS.get(S(case.state))
        if fn is None or not fn(db, case):
            return
        case.updated_at = clock.now()


def step_intake(db: Session, case: Case) -> bool:
    if not case.event_type:
        say(db, case, hi.ASK_EVENT, ask="event_type")
        return False
    if not case.crop_reported:
        say(db, case, hi.ASK_CROP, ask="crop")
        return False
    ctype = case.claim_type
    if ctype == ClaimType.WIDESPREAD.value:
        if not case.event_at and case.flag("event_time_unresolved"):
            pass  # timing does not drive a deadline for area-based claims
        decide(db, case, "route_area_based",
               f"{case.event_type} is assessed on insurance-unit yield (CCE), not by individual survey; "
               "no 72-hour intimation needed. Keep case open for yield data.")
        say(db, case, hi.widespread_note(case))
        case.season = case.season or yield_engine.season_for(case.event_at or clock.now())
        case.state = S.GATHER.value
        return True
    if not case.event_at:
        say(db, case, hi.ASK_TIME, ask="event_time")
        return False
    deadline = case.event_at + timedelta(hours=config.REPORT_WINDOW_H)
    set_fact(db, case, "deadline_at", deadline, FactSource.AGENT_ESTIMATE, note="event time + 72 hours")
    case.season = yield_engine.season_for(case.event_at)
    decide(db, case, "compute_deadline", f"event {case.event_at:%d %b %H:%M} + 72h = {deadline:%d %b %H:%M}",
           {"claim_type": ctype})
    case.state = S.DEADLINE_CONFIRM.value
    consent.propose(db, case, ActionKind.CONFIRM_DEADLINE.value,
                    hi.deadline_readback(case.event_type, case.event_at, deadline, case.crop_reported,
                                         assumed_time=bool(case.flag("time_assumed"))),
                    ["event_type", "event_at", "crop_reported", "deadline_at"],
                    reason="deadline must be confirmed before anything is filed against it")
    return False


def step_deadline_confirm(db: Session, case: Case) -> bool:
    return False  # waiting on consent


def _lookup_policy(db: Session, case: Case) -> Optional[bool]:
    """True = found, False = waiting on farmer, None = nothing to try."""
    tried = list(case.flag("lookups_tried") or [])
    receipt, loan, otp = case.flag("receipt_no"), case.flag("loan_account"), case.flag("otp")
    res = None
    if receipt and f"r:{receipt}" not in tried:
        tried.append(f"r:{receipt}")
        res = policy_lookup.by_receipt(receipt)
    elif loan and f"l:{loan}:{otp}" not in tried:
        tried.append(f"l:{loan}:{otp}")
        res = policy_lookup.by_loan_account(loan, otp=otp)
    case.set_flag("lookups_tried", tried)
    if res is None:
        return None
    decide(db, case, f"policy_lookup:{res['via']}", f"result: {res['status']} [MOCK]")
    if res["status"] == "needs_otp":
        say(db, case, hi.ASK_OTP, ask="otp")
        return False
    if res["status"] == "otp_wrong":
        case.set_flag("otp", None)
        say(db, case, "OTP सही नहीं निकला। कृपया दोबारा देखकर भेजिए।", ask="otp")
        return False
    if res["status"] == "not_found":
        what = "रसीद नंबर" if res["via"] == "receipt" else "लोन खाता नंबर"
        say(db, case, f"इस {what} से कोई पॉलिसी नहीं मिली [MOCK पोर्टल]। कृपया नंबर दोबारा जांचें, या दूसरा "
                      f"पहचान नंबर भेजें।\n{hi.ASK_POLICY}", ask="policy_id")
        return False
    p = res["policy"]
    case.set_flag("policy", p)
    case.farmer_name_masked = p["farmer_name_masked"]
    kw = dict(mock=True, illustrative=p.get("illustrative", False))
    set_fact(db, case, "policy_no", p["policy_no"], FactSource.PORTAL, **kw)
    set_fact(db, case, "crop_insured", p["crop"], FactSource.PORTAL, **kw, note=p.get("_toggle"))
    set_fact(db, case, "iu_code", p["iu_code"], FactSource.PORTAL, **kw)
    set_fact(db, case, "insured_area_ha", p["area_ha"], FactSource.PORTAL, **kw)
    set_fact(db, case, "sum_insured", round(p["area_ha"] * p["sum_insured_per_ha"]), FactSource.PORTAL, **kw)
    if not case.village:
        set_fact(db, case, "village", p["village"], FactSource.PORTAL, **kw)
    set_fact(db, case, "khasra", p["khasra"][0], FactSource.PORTAL, **kw)
    if not case.season:
        case.season = p["season"]
    say(db, case, f"पॉलिसी मिल गई ✅ [MOCK पोर्टल]\n• पॉलिसी: {p['policy_no']}\n• बीमित फसल: {hi.crop(p['crop'])}\n"
                  f"• खेत: {p['village']}, खसरा {', '.join(p['khasra'])}\n• बीमित रकबा: {hi.area(p['area_ha'])}")
    return True


def step_gather(db: Session, case: Case) -> bool:
    now = clock.now()
    widespread = case.claim_type == ClaimType.WIDESPREAD.value

    # 0. Honest about a missed deadline, but keep going.
    if not widespread and case.deadline_at and now > case.deadline_at and not case.flag("late_noted"):
        case.set_flag("late_noted", True)
        decide(db, case, "continue_after_deadline", "72h already passed; report anyway and keep proof")
        say(db, case, "72 घंटे की समय-सीमा निकल चुकी है। फिर भी मैं रिपोर्ट दर्ज करने की पूरी कोशिश करूँगा और हर "
                      "कोशिश का रिकॉर्ड रखूँगा, ताकि बाद में देरी का कारण साबित किया जा सके।")

    # 1. Policy (needed for everything else)
    if not case.policy_no:
        r = _lookup_policy(db, case)
        if r is None:
            if case.flag("awaiting") != "policy_id":
                say(db, case, hi.ASK_POLICY, ask="policy_id")
            return False
        return bool(r)

    p = _policy(case)
    # 2. Damaged plot vs insured plot (Apna Khata)
    if not case.flag("land_checked"):
        case.set_flag("land_checked", True)
        m = land_records.match(case.village, case.flag("farmer_khasra"), p)
        set_fact(db, case, "plot_match", m["status"], FactSource.FIXTURE)
        decide(db, case, "land_record_check", f"Apna Khata (fixture): {m['status']}")
        if m["status"] == "different_plot":
            ins = ", ".join(k for _, k in m["insured"])
            say(db, case, f"ध्यान दें: आपने खसरा {case.flag('farmer_khasra')} बताया, लेकिन बीमा खसरा {ins} पर है। "
                          f"क्लेम सिर्फ बीमित खेत पर बनता है। आगे की रिपोर्ट खसरा {ins} के लिए होगी — अगर नुकसान उस "
                          "खेत में नहीं हुआ तो रिपोर्ट के समय *नहीं* कहें।")

    # 3. Crop mismatch -> stop
    photo_crop = case.flag("photo_crop")
    sown = case.crop_reported or photo_crop
    if case.crop_insured and sown and sown != case.crop_insured:
        decide(db, case, "stop_crop_mismatch",
               f"policy says {case.crop_insured}, farmer/photo say {sown}: a claim would be rejected; route to "
               "enrolment correction instead of filing", {"photo_crop": photo_crop})
        case.state = S.CROP_MISMATCH.value
        return True

    # 4. Area-based route: nothing to file; wait for yield data
    if widespread:
        info = yield_engine.season_info(case.season or p["season"]) or {}
        exp = datetime.fromisoformat(info["expected_publish"]) if info.get("expected_publish") else now
        due = max(exp.replace(hour=10), now)
        record.schedule(db, case, CheckKind.YIELD_CHECK, due, "expected yield publication")
        decide(db, case, "await_yield_data", f"yield data for {case.season} expected around {exp:%d %b %Y}")
        say(db, case, f"केस खुला है। {case.season} की उपज के आंकड़े लगभग {hi.when(exp).rsplit(' ', 3)[0]} "
                      "तक आने की उम्मीद है। तब मैं खुद आपको बताऊँगा कि क्लेम बनता है या नहीं, और कितना। "
                      "इसके लिए किसी एजेंट को पैसे न दें।")
        case.state = S.AWAIT_YIELD_DATA.value
        return True

    # 5. Weather corroboration (never blocks)
    if not case.flag("weather_done") and case.event_at:
        w = weather.corroborate(case.village, case.event_type, case.event_at)
        case.set_flag("weather_done", w["verdict"])
        set_fact(db, case, "weather", f"{w['verdict']}: {w['why']}", w["source"],
                 illustrative=w["source"] == "fixture", note=w["source_note"])
        decide(db, case, f"weather:{w['verdict']}", w["why"] + f" ({w['source_note']})")
        if w["verdict"] == "inconsistent" and not case.flag("weather_asked"):
            case.set_flag("weather_asked", True)
            case.set_flag("weather_reconfirm_open", True)  # next free-text reply is kept as the farmer's version
            say(db, case, f"मौसम रिकॉर्ड में {hi.when(case.event_at).split(' ')[0]} {hi.MONTH_HI[case.event_at.month - 1]} "
                          f"के आसपास आपके गांव में {hi.event(case.event_type)} दर्ज नहीं दिखता ({w['why']}).\n"
                          "यह गलत भी हो सकता है — ओले अक्सर बहुत छोटे इलाके में गिरते हैं। कृपया एक बार फिर बताइए कि "
                          "ठीक क्या हुआ था। मैं आपकी बात और रिकॉर्ड, दोनों दर्ज रखूँगा।", ask="weather_reconfirm")

    # 6. Area (only a farmer-stated figure is ever used)
    if case.area_ha is None:
        say(db, case, hi.ASK_AREA, ask="area")
        return False
    if case.insured_area_ha and case.area_ha > case.insured_area_ha * 1.02:
        if case.flag("awaiting") != "area":
            say(db, case, f"बीमा {hi.area(case.insured_area_ha)} का है, और आपने {hi.area(case.area_ha)} बताया। "
                          "क्लेम बीमित रकबे से ज़्यादा का नहीं हो सकता। कितने रकबे में नुकसान हुआ?", ask="area")
        return False

    # 7. Evidence: wait for photos unless the deadline is close
    valid = valid_photo_count(db, case)
    h = _hours_left(case, now)
    if valid < config.MIN_VALID_PHOTOS:
        if h is not None and h <= config.REPORT_NOW_THRESHOLD_H:
            decide(db, case, "report_now_without_full_evidence",
                   f"{valid}/{config.MIN_VALID_PHOTOS} valid photos but only {h:.0f}h left "
                   f"(threshold {config.REPORT_NOW_THRESHOLD_H:.0f}h); photos can be attached after filing")
        elif case.flag("no_photos"):
            decide(db, case, "report_without_photos", "farmer has no photos now; filing first, photos later")
        else:
            if not case.flag("photos_asked"):
                case.set_flag("photos_asked", True)
                decide(db, case, "wait_for_photos",
                       f"{valid}/{config.MIN_VALID_PHOTOS} valid photos, {h:.0f}h left > threshold "
                       f"{config.REPORT_NOW_THRESHOLD_H:.0f}h")
                say(db, case, hi.ask_photos(capture_link(case), hi.hours_left(case.deadline_at, now)), ask="photos")
            return False

    # 8. Read-back before filing
    first_open = next((c for c in config.CHANNEL_ORDER if channels.is_open(c, now)), config.CHANNEL_ORDER[0])
    fields = [k for k in ("policy_no", "event_type", "event_at", "crop_insured", "area_ha", "village", "khasra")
              if record.latest_fact(db, case, k) is not None]
    case.state = S.REPORT_CONSENT.value
    consent.propose(db, case, ActionKind.REPORT_LOSS.value, hi.report_readback(case, channels.LABEL_HI[first_open]),
                    fields, reason=f"ready to file: policy found, {valid} valid photos, "
                                   f"{'' if h is None else f'{h:.0f}h left'}")
    return False


def step_crop_mismatch(db: Session, case: Case) -> bool:
    if case.flag("correction_proposed"):
        return False
    case.set_flag("correction_proposed", True)
    sown = case.crop_reported or case.flag("photo_crop")
    consent.propose(db, case, ActionKind.ENROLMENT_CORRECTION.value,
                    hi.correction_readback(case, case.crop_insured, sown), ["crop_insured", "crop_reported"],
                    extra={"insured": case.crop_insured, "sown": sown},
                    reason="crop mismatch: offer correction request instead of filing a claim that would be rejected")
    return False


# ------------------------------------------------------------------ reporting chain
def run_reporting(db: Session, case: Case) -> bool:
    now = clock.now()
    order = config.CHANNEL_ORDER
    succeeded = False
    for i, ch in enumerate(order):
        if not channels.is_open(ch, now):
            decide(db, case, f"skip:{ch}", f"{ch} closed at {now:%a %H:%M}; next open {channels.next_open(ch, now):%a %H:%M}")
            continue
        n = (db.scalar(select(func.count()).select_from(ChannelAttempt).where(
            ChannelAttempt.case_id == case.id, ChannelAttempt.channel == ch)) or 0) + 1
        r = channels.attempt(ch, {"policy_no": case.policy_no}, attempt_no=n, seed=case.id)
        result = r.result
        if result == "ok" and not channels.valid_ref(ch, r.ref_no):
            result = "invalid_ref"
        db.add(ChannelAttempt(case_id=case.id, channel=ch, started_at=now, result=result, ref_no=r.ref_no,
                              raw=r.raw, mock=True))
        db.flush()
        if result == "ok":
            set_fact(db, case, "reference_no", r.ref_no, FactSource.INSURER, mock=True, note=f"via {ch}")
            case.report_channel = ch
            case.reported_at = now
            decide(db, case, f"reported:{ch}", f"valid reference {r.ref_no} [MOCK]", {"attempt": n})
            succeeded = True
            break
        nxt = next((c for c in order[i + 1:] if channels.is_open(c, now)), None)
        decide(db, case, f"channel_failed:{ch}", f"{result}: {r.raw}" + (f"; switching to {nxt}" if nxt else ""))
        msg = f"{channels.LABEL_HI[ch]} से रिपोर्ट नहीं हो पाई ({result}) [MOCK]।"
        if nxt:
            msg += f" अब {channels.LABEL_HI[nxt]} से कोशिश कर रहा हूँ — {hi.hours_left(case.deadline_at, now)}।"
        say(db, case, msg)
    if succeeded:
        case.state = S.REPORTED.value
        return True
    attempts = db.scalars(select(ChannelAttempt).where(ChannelAttempt.case_id == case.id)
                          .order_by(ChannelAttempt.id)).all()
    pdf = documents.attempt_log(case, attempts, now)
    db.add(Evidence(case_id=case.id, kind="document", received_at=now, path=pdf, title="Attempt log (proof)",
                    valid=True))
    retry_at = min([channels.next_open(c, now) for c in order if not channels.is_open(c, now)] + [now + timedelta(hours=2)])
    record.schedule(db, case, CheckKind.RETRY_REPORT, retry_at, "all channels failed")
    decide(db, case, "all_channels_failed", f"{len(attempts)} attempts logged; retry at {retry_at:%d %b %H:%M}")
    say(db, case, f"अभी कोई भी रास्ता काम नहीं कर रहा [MOCK]। हर कोशिश का समय और जवाब रिकॉर्ड कर लिया है (PDF सबूत "
                  f"संलग्न)। मैं {hi.when(retry_at)} फिर कोशिश करूँगा। {hi.hours_left(case.deadline_at, now)}।",
        media_path=pdf, media_kind="document")
    if case.deadline_at and now > case.deadline_at:
        case.state = S.DEADLINE_MISSED_WITH_PROOF.value
        case.outcome = Outcome.DEADLINE_MISSED_WITH_PROOF.value
    return False


def step_reported(db: Session, case: Case) -> bool:
    now = clock.now()
    pdf = documents.report_receipt(case, now)
    db.add(Evidence(case_id=case.id, kind="document", received_at=now, path=pdf, title="Report receipt", valid=True))
    on_time = case.deadline_at is None or case.reported_at <= case.deadline_at
    say(db, case, f"✅ नुकसान दर्ज हो गया [MOCK]।\n• रेफरेंस नंबर: *{case.reference_no}*\n"
                  f"• रास्ता: {channels.LABEL_HI[case.report_channel]}\n• समय: {hi.when(case.reported_at)} "
                  f"({'समय-सीमा के अंदर' if on_time else 'समय-सीमा के बाद'})\n\n{hi.DONT_CLEAR}\n"
                  "आगे: 10 दिन के अंदर सर्वेयर को खेत देखना होता है। मैं हर 3 दिन स्टेटस देखूँगा। "
                  f"फोटो अभी भी भेज सकते हैं: {capture_link(case)}", media_path=pdf, media_kind="document")
    record.cancel_checks(db, case, [CheckKind.DEADLINE_WARNING.value, CheckKind.REPORT_NOW.value,
                                    CheckKind.RETRY_REPORT.value])
    if case.outcome == Outcome.DEADLINE_MISSED_WITH_PROOF.value:
        case.outcome = None  # late report still filed; outcome decided by follow-up
    case.state = S.AWAIT_SURVEY.value
    record.schedule(db, case, CheckKind.STATUS_POLL, now + timedelta(days=3), "survey status")
    info = yield_engine.season_info(case.season or "")
    if info:  # also watch the area-based route for this IU
        record.schedule(db, case, CheckKind.YIELD_CHECK, datetime.fromisoformat(info["expected_publish"]).replace(hour=10),
                        "area route check")
    decide(db, case, "start_follow_up", "localised/post-harvest claim: track survey -> assessment -> payment")
    return True


# ------------------------------------------------------------------ follow-up
def _status(case: Case, now: datetime) -> dict:
    payable_at = case.flag("payable_at")
    return claim_status.get(_policy(case), claim_type=case.claim_type,
                            reported_at=case.reported_at,
                            payable_at=datetime.fromisoformat(payable_at) if payable_at else None,
                            estimate_inr=case.flag("estimate_inr"), now=now, grievances=_grievances(case))


def _record_status(db: Session, case: Case, st: dict) -> None:
    sig = f"{st['survey']}|{st['assessed_loss_pct']}|{st['payment_status']}|{st.get('code')}"
    if case.flag("status_sig") != sig:
        case.set_flag("status_sig", sig)
        case.set_flag("status_changed_at", clock.now().isoformat())
        set_fact(db, case, "claim_status", sig, FactSource.INSURER, mock=True)


def follow_up_poll(db: Session, case: Case) -> None:
    now = clock.now()
    st = _status(case, now)
    _record_status(db, case, st)
    for _ in range(6):
        state = S(case.state)
        if state == S.AWAIT_SURVEY:
            if st["survey"] == "done":
                decide(db, case, "survey_done", "status feed shows survey completed [MOCK]")
                say(db, case, "सर्वेयर ने आपके खेत का सर्वे कर लिया है [MOCK स्टेटस]। अब नुकसान का आकलन आएगा।")
                case.state = S.AWAIT_ASSESSMENT.value
                continue
            days = (now - case.reported_at).days
            if days >= config.SURVEY_SLA_DAYS and "survey" not in _grievances(case) and not case.flag("survey_grievance_proposed"):
                case.set_flag("survey_grievance_proposed", True)
                decide(db, case, "escalate_survey", f"no survey {days} days after intimation (> {config.SURVEY_SLA_DAYS})")
                consent.propose(db, case, ActionKind.GRIEVANCE.value,
                                hi.grievance_readback(case, f"{days} दिन बाद भी सर्वे नहीं हुआ", "कृषि रक्षक पोर्टल / 14447"),
                                ["reference_no", "policy_no"], extra={"topic": "survey", "then_state": S.AWAIT_SURVEY.value,
                                                                      "detail": f"No loss survey {days} days after intimation {case.reference_no}."})
            record.schedule(db, case, CheckKind.STATUS_POLL, now + timedelta(days=3), "survey status")
            return
        if state == S.AWAIT_ASSESSMENT:
            if st["assessed_loss_pct"] is not None:
                pct = st["assessed_loss_pct"]
                set_fact(db, case, "assessed_loss_pct", f"{pct}%", FactSource.INSURER, mock=True)
                share = (case.area_ha / case.insured_area_ha) if case.insured_area_ha else 1.0
                est = round(pct / 100 * (case.sum_insured or 0) * min(1.0, share))
                set_fact(db, case, "estimate_inr", est, FactSource.AGENT_ESTIMATE,
                         note=f"{pct}% x sum insured x affected share {share:.2f}")
                case.set_flag("estimate_inr", est)
                case.set_flag("payable_at", st["assessed_at"].isoformat())
                decide(db, case, "assessment_received", f"loss {pct}% -> estimate Rs {est}")
                facts = [record.latest_fact(db, case, k) for k in ("area_ha", "assessed_loss_pct", "sum_insured", "estimate_inr")]
                say(db, case, "सर्वे का आकलन आ गया:\n\n" + hi.grouped([f for f in facts if f]))
                case.state = S.AWAIT_PAYMENT.value
                st = _status(case, now)
                continue
            record.schedule(db, case, CheckKind.STATUS_POLL, now + timedelta(days=3), "assessment status")
            return
        if state in (S.AWAIT_PAYMENT, S.BLOCKED):
            if st["payment_status"] == "paid":
                amt = st.get("paid_amount") or case.flag("estimate_inr")
                set_fact(db, case, "payment", f"{hi.rupees(amt)} on {st['paid_on']:%d %b %Y}", FactSource.INSURER, mock=True)
                case.paid_amount = amt
                decide(db, case, "close_paid", f"payment of Rs {amt} confirmed by status feed [MOCK]")
                say(db, case, f"🎉 क्लेम का भुगतान हो गया [MOCK स्टेटस]: *{hi.rupees(amt)}*, {hi.when(st['paid_on']).rsplit(' ', 3)[0]}। "
                              "अपनी पासबुक में एंट्री ज़रूर मिलाएं। केस बंद किया जा रहा है।")
                _close(db, case, S.CLOSED_PAID, Outcome.PAID)
                return
            if state == S.BLOCKED:
                record.schedule(db, case, CheckKind.STATUS_POLL, now + timedelta(days=30), "re-check blocked claim")
                return
            changed = datetime.fromisoformat(case.flag("status_changed_at"))
            if st["payment_status"] in ("failed", "pending") or (now - changed).days > config.STATUS_STALL_DAYS:
                decide(db, case, "diagnose_unpaid", f"payable but unpaid: status={st['payment_status']} code={st.get('code')}")
                case.state = S.DIAGNOSE.value
                continue
            record.schedule(db, case, CheckKind.STATUS_POLL, now + timedelta(days=7), "payment status")
            return
        if state == S.DIAGNOSE:
            diagnose(db, case, st)
            return
        return


def diagnose(db: Session, case: Case, st: dict) -> None:
    now = clock.now()
    p = _policy(case)
    done = list(case.flag("diag_done") or [])
    for check, why in diagnosis.plan_order(st):
        if check in done:
            continue
        done.append(check)
        case.set_flag("diag_done", done)
        res = {"bank": lambda: diagnosis.check_bank(p), "mapping": lambda: diagnosis.check_mapping(p),
               "subsidy": lambda: diagnosis.check_subsidy(case.season or p.get("season"))}[check]()
        decide(db, case, f"check:{check}", f"{why} -> {'FOUND: ' + res['blocker'] if res['found'] else res.get('detail')}")
        set_fact(db, case, f"diag_{check}", res.get("blocker") or res.get("detail"), res["source"],
                 mock=res.get("mock", False), illustrative=res.get("illustrative", False))
        if not res["found"]:
            continue
        case.blocker, case.next_step = res["blocker"], res["next_step"]
        if res["grievance"]:
            consent.propose(db, case, ActionKind.GRIEVANCE.value,
                            hi.grievance_readback(case, res["blocker_hi"], "कृषि रक्षक पोर्टल / DGRC अलवर"),
                            ["policy_no"], extra={"topic": "payment", "then_state": S.BLOCKED.value,
                                                  "detail": res["blocker"] + ". " + res["next_step"],
                                                  "next_step_hi": res["next_step_hi"]})
        else:
            say(db, case, f"भुगतान क्यों रुका है: {res['blocker_hi']}।\n{res['next_step_hi']}")
            case.state = S.BLOCKED.value
            case.outcome = Outcome.BLOCKED.value
            record.schedule(db, case, CheckKind.STATUS_POLL, now + timedelta(days=30), "re-check subsidy release")
        return
    # nothing found: generic escalation with what was checked
    case.blocker = "Unpaid; bank, mapping and subsidy checks found no cause"
    case.next_step = "Grievance to insurer via Krishi Rakshak 14447 asking for the specific reason"
    consent.propose(db, case, ActionKind.GRIEVANCE.value,
                    hi.grievance_readback(case, "क्लेम बनता है पर भुगतान नहीं हुआ, कारण बताया जाए", "कृषि रक्षक पोर्टल / 14447"),
                    ["policy_no"], extra={"topic": "payment", "then_state": S.BLOCKED.value, "detail": case.blocker,
                                          "next_step_hi": "बीमा कंपनी से लिखित कारण मांगा गया है।"})


def yield_check(db: Session, case: Case) -> None:
    now = clock.now()
    p = _policy(case)
    season = case.season or p.get("season")
    res = yield_engine.evaluate(case.iu_code, case.crop_insured, season, case.sum_insured or 0, now.date())
    area_route_only = case.claim_type != ClaimType.WIDESPREAD.value
    if not res["published"]:
        exp = datetime.fromisoformat(res["expected_publish"]) if res.get("expected_publish") else now
        if area_route_only:
            return
        if now > exp + timedelta(days=config.YIELD_RTI_GRACE_DAYS) and not case.flag("rti_proposed"):
            case.set_flag("rti_proposed", True)
            decide(db, case, "propose_rti", f"yield data for {case.iu_code}/{season} not published "
                                            f"{(now - exp).days} days after expected date")
            consent.propose(db, case, ActionKind.RTI.value, hi.rti_readback(case, case.iu_code, season),
                            ["policy_no"], extra={"iu": case.iu_code, "season": season, "crop": case.crop_insured})
        else:
            decide(db, case, "wait_yield_data", f"not published yet (expected {exp:%d %b %Y})")
        record.schedule(db, case, CheckKind.YIELD_CHECK, max(now, exp) + timedelta(days=14), "yield data re-check")
        return
    kw = dict(illustrative=res["illustrative"], note=res.get("source_url") or "illustrative dataset")
    set_fact(db, case, "actual_yield", f"{res['actual_kg_ha']} kg/ha", FactSource.RECORD, **kw)
    set_fact(db, case, "threshold_yield", f"{res['threshold_kg_ha']} kg/ha", FactSource.RECORD, **kw)
    figures = (f"• इकाई {case.iu_code}, {hi.crop(case.crop_insured)}, {season}\n"
               f"• वास्तविक उपज (CCE): {res['actual_kg_ha']} किलो/हेक्टेयर\n"
               f"• थ्रेशोल्ड उपज: {res['threshold_kg_ha']} किलो/हेक्टेयर "
               f"(पिछले 7 में से सबसे अच्छे 5 साल का औसत × {int(res['indemnity_level'] * 100)}%)"
               + ("\n[उदाहरण डेटा — असली प्रकाशित आंकड़े नहीं]" if res["illustrative"] else ""))
    if area_route_only:
        set_fact(db, case, "area_route", "payable" if res["payable"] else "not payable", FactSource.RECORD, **kw)
        decide(db, case, "area_route_checked", f"IU yield route: payable={res['payable']} (individual claim continues)")
        return
    if not res["payable"]:
        decide(db, case, "close_not_payable", f"actual {res['actual_kg_ha']} >= threshold {res['threshold_kg_ha']}")
        say(db, case, "उपज के आंकड़े आ गए हैं:\n" + figures +
            "\n\nआपकी इकाई की उपज थ्रेशोल्ड से *ऊपर* रही, इसलिए इस इकाई में किसी को भी इस नुकसान का क्लेम नहीं बनता — "
            "चाहे एक खेत में नुकसान ज़्यादा दिखा हो। कोई एजेंट पैसे लेकर क्लेम दिलाने का वादा करे तो सावधान रहें।"
            "\nकेस बंद किया जा रहा है।")
        _close(db, case, S.CLOSED_NOT_PAYABLE, Outcome.NOT_PAYABLE)
        return
    est = res["claim_inr"]
    set_fact(db, case, "estimate_inr", est, FactSource.AGENT_ESTIMATE,
             note=f"shortfall {res['shortfall']:.1%} x sum insured {res['sum_insured']}")
    case.set_flag("estimate_inr", est)
    case.set_flag("payable_at", datetime.fromisoformat(res["published_on"]).isoformat())
    decide(db, case, "payable_area_based", f"shortfall {res['shortfall']:.1%} -> estimate Rs {est}")
    say(db, case, "उपज के आंकड़े आ गए हैं:\n" + figures +
        f"\n\nइकाई की उपज थ्रेशोल्ड से कम है, कमी {res['shortfall']:.0%}।\n*मेरा अंदाज़ा (पक्का नहीं):* क्लेम लगभग "
        f"{hi.rupees(est)}। मैं भुगतान पर नज़र रखूँगा।")
    case.state = S.AWAIT_PAYMENT.value
    case.set_flag("status_changed_at", now.isoformat())
    follow_up_poll(db, case)


# ------------------------------------------------------------------ scheduled checks
def on_check(db: Session, case: Case, check: ScheduledCheck) -> None:
    kind = CheckKind(check.kind)
    now = clock.now()
    state = S(case.state)
    if kind == CheckKind.DEADLINE_WARNING:
        if state in (S.GATHER, S.REPORT_CONSENT, S.DEADLINE_CONFIRM, S.INTAKE) and case.deadline_at:
            what = "ऊपर वाली रिपोर्ट की पुष्टि (हाँ/नहीं)" if consent.pending(db, case) else "जो जानकारी मांगी है वह"
            say(db, case, f"⏰ याद दिलाना: {hi.hours_left(case.deadline_at, now)}। कृपया {what} भेजिए ताकि रिपोर्ट समय पर दर्ज हो।")
    elif kind == CheckKind.REPORT_NOW:
        if state == S.GATHER:
            advance(db, case)
    elif kind == CheckKind.RETRY_REPORT:
        if state in (S.REPORTING, S.DEADLINE_MISSED_WITH_PROOF):
            if run_reporting(db, case):
                advance(db, case)
    elif kind == CheckKind.STATUS_POLL:
        if state in (S.AWAIT_SURVEY, S.AWAIT_ASSESSMENT, S.AWAIT_PAYMENT, S.DIAGNOSE, S.BLOCKED):
            if not consent.pending(db, case):
                follow_up_poll(db, case)
            else:
                record.schedule(db, case, CheckKind.STATUS_POLL, now + timedelta(days=3), "waiting on consent")
    elif kind == CheckKind.YIELD_CHECK:
        if state == S.AWAIT_YIELD_DATA or (state not in (S.CLOSED_PAID, S.CLOSED_NOT_PAYABLE) and case.claim_type != ClaimType.WIDESPREAD.value):
            yield_check(db, case)


# ------------------------------------------------------------------ executors (reachable only via consent)
@consent.executor(ActionKind.CONFIRM_DEADLINE.value)
def _exec_confirm_deadline(db: Session, case: Case, a: Action) -> dict:
    d = case.deadline_at
    case.state = S.GATHER.value
    for hrs in (24, 6):
        if d - timedelta(hours=hrs) > clock.now():
            record.schedule(db, case, CheckKind.DEADLINE_WARNING, d - timedelta(hours=hrs), f"-{hrs}h", replace=False)
    record.schedule(db, case, CheckKind.REPORT_NOW, max(clock.now(), d - timedelta(hours=config.REPORT_NOW_THRESHOLD_H)),
                    "report even without full evidence")
    say(db, case, "धन्यवाद, समय-सीमा पक्की हुई ✅। अब आपकी बीमा पॉलिसी देखते हैं।")
    advance(db, case)
    return {"deadline": d.isoformat()}


@consent.executor(ActionKind.REPORT_LOSS.value)
def _exec_report(db: Session, case: Case, a: Action) -> dict:
    case.state = S.REPORTING.value
    ok = run_reporting(db, case)
    if ok:
        advance(db, case)
    return {"reported": ok, "reference_no": case.reference_no}


@consent.executor(ActionKind.GRIEVANCE.value)
def _exec_grievance(db: Session, case: Case, a: Action) -> dict:
    now = clock.now()
    topic = a.payload["topic"]
    pdf = documents.grievance(case, topic, a.payload.get("detail", ""), now)
    ref = f"GRV-{case.id:04d}-{now:%m%d%H%M}"
    g = dict(case.flag("grievances") or {})
    g[topic] = now.isoformat()
    case.set_flag("grievances", g)
    db.add(Evidence(case_id=case.id, kind="document", received_at=now, path=pdf, title=f"Grievance ({topic})", valid=True))
    set_fact(db, case, f"grievance_{topic}", ref, FactSource.PORTAL, mock=True)
    msg = f"शिकायत दर्ज हो गई [MOCK]। शिकायत नंबर: *{ref}*।"
    if a.payload.get("next_step_hi"):
        msg += f"\n\nआगे आपको यह करना है: {a.payload['next_step_hi']}"
    say(db, case, msg, media_path=pdf, media_kind="document")
    then = a.payload.get("then_state")
    if then:
        case.state = then
        if then == S.BLOCKED.value:
            case.outcome = Outcome.BLOCKED.value
    record.schedule(db, case, CheckKind.STATUS_POLL, now + timedelta(days=3 if topic == "survey" else 30),
                    f"after grievance ({topic})")
    return {"ref": ref, "pdf": pdf}


@consent.executor(ActionKind.RTI.value)
def _exec_rti(db: Session, case: Case, a: Action) -> dict:
    now = clock.now()
    pdf = documents.rti(case, a.payload["iu"], a.payload["crop"], a.payload["season"], now)
    db.add(Evidence(case_id=case.id, kind="document", received_at=now, path=pdf, title="RTI draft", valid=True))
    say(db, case, "RTI आवेदन का ड्राफ्ट तैयार है (PDF)। इसे ₹10 फीस के साथ लोक सूचना अधिकारी, कृषि निदेशालय, जयपुर को "
                  "भेजें, या ई-मित्र से ऑनलाइन जमा करवाएं। मैं उपज के आंकड़े देखता रहूँगा।",
        media_path=pdf, media_kind="document")
    return {"pdf": pdf}


@consent.executor(ActionKind.ENROLMENT_CORRECTION.value)
def _exec_correction(db: Session, case: Case, a: Action) -> dict:
    now = clock.now()
    pdf = documents.enrolment_correction(case, a.payload["insured"], a.payload["sown"], now)
    db.add(Evidence(case_id=case.id, kind="document", received_at=now, path=pdf, title="Enrolment correction", valid=True))
    bank = (_policy(case).get("bank") or {}).get("name", "जिस बैंक/CSC से बीमा हुआ")
    case.blocker = f"Crop in enrolment ({a.payload['insured']}) differs from sown crop ({a.payload['sown']})"
    case.next_step = f"Submit correction request at {bank}; copy to insurer district office"
    case.state = S.BLOCKED.value
    case.outcome = Outcome.BLOCKED.value
    say(db, case, f"सुधार अनुरोध तैयार है (PDF)। इसे लेकर *{bank}* जाएं और बीमा कंपनी के जिला ऑफिस को कॉपी दें। "
                  "गलत फसल पर क्लेम दर्ज नहीं किया गया है।", media_path=pdf, media_kind="document")
    return {"pdf": pdf}


_STEPS = {
    S.INTAKE: step_intake,
    S.DEADLINE_CONFIRM: step_deadline_confirm,
    S.GATHER: step_gather,
    S.CROP_MISMATCH: step_crop_mismatch,
    S.REPORTED: step_reported,
}
