"""Judge dashboard: WhatsApp-style simulator + case internals (provenance, decisions, attempts, consent),
fault injection, clock control, and the three scripted demos.

Run:  streamlit run dashboard/app.py
"""
from __future__ import annotations

import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402
from PIL import Image  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app import clock, config, demo, kv  # noqa: E402
from app.db import init_db, session_scope  # noqa: E402
from app.engine import scheduler  # noqa: E402
from app.engine.faq import STATE_HI  # noqa: E402
from app.models.case import (Action, Case, ChannelAttempt, Decision, Evidence, Fact, Message,  # noqa: E402
                             ScheduledCheck)
from app.responses import hi  # noqa: E402
from app.tools import geo  # noqa: E402
from app.tools.reporting import channels  # noqa: E402

st.set_page_config(page_title="Saakshi — Kisan Sahayak", page_icon="🌾", layout="wide")
init_db()

SOURCE_COLOURS = {"farmer": "#dbeafe", "portal": "#dcfce7", "record": "#dcfce7", "insurer": "#dcfce7",
                  "bank": "#dcfce7", "land_record": "#dcfce7", "weather": "#e0f2fe", "fixture": "#fef9c3",
                  "agent_estimate": "#fde68a"}
BEHAVIOURS = ["ok", "error", "timeout", "no_answer", "invalid_ref", "error_once", "timeout_once"]


# ---------------------------------------------------------------- sidebar
with st.sidebar:
    st.title("🌾 Saakshi")
    now = clock.now()
    st.markdown(f"**Simulated time (IST)**  \n### {now:%d %b %Y, %H:%M}")
    c1, c2, c3 = st.columns(3)
    jumps = {"+1 h": timedelta(hours=1), "+1 day": timedelta(days=1), "+3 days": timedelta(days=3),
             "+1 week": timedelta(weeks=1), "+1 month": timedelta(days=30), "+3 months": timedelta(days=91)}
    for i, (label, delta) in enumerate(jumps.items()):
        if [c1, c2, c3][i % 3].button(label, use_container_width=True):
            n = scheduler.advance_clock(delta)
            st.toast(f"Clock moved {label}; {n} scheduled checks ran")
            st.rerun()
    with st.expander("Set clock"):
        d = st.date_input("Date", now.date())
        t = st.time_input("Time", now.time().replace(second=0, microsecond=0))
        if st.button("Set (no checks fire)"):
            clock.set_to(datetime.combine(d, t))
            st.rerun()
        if st.button("Jump to here (fire checks)"):
            target = datetime.combine(d, t)
            if target > now:
                scheduler.advance_clock(target - now)
            st.rerun()

    st.subheader("Fault injection")
    faults = kv.faults()
    for ch in config.CHANNEL_ORDER:
        cur = faults.get(ch, "ok")
        new = st.selectbox(ch, BEHAVIOURS, index=BEHAVIOURS.index(cur) if cur in BEHAVIOURS else 0, key=f"f_{ch}")
        if new != cur:
            kv.set_fault(ch, new)
    mm = st.toggle("Crop-mismatch toggle (policy shows other crop)", value=bool(kv.get("force_crop_mismatch", False)))
    if mm != bool(kv.get("force_crop_mismatch", False)):
        kv.set("force_crop_mismatch", mm)

    st.subheader("Scripted demos")
    if st.button("1 · Hail + app outage → helpline ref → paid", use_container_width=True):
        cid = demo.demo1_hail_app_outage()
        st.session_state.phone = demo.DEMO1_PHONE
        st.toast("Demo 1 loaded. Use '+3 days' / '+1 month' to follow the claim.")
        st.rerun()
    if st.button("2 · Payable, unseeded account → grievance", use_container_width=True):
        demo.demo2_payable_unseeded()
        st.session_state.phone = demo.DEMO2_PHONE
        st.rerun()
    if st.button("3 · IU above threshold → no payout due", use_container_width=True):
        demo.demo3_not_payable()
        st.session_state.phone = demo.DEMO3_PHONE
        st.rerun()

    st.subheader("Farmer")
    st.session_state.setdefault("phone", "+919812345678")
    st.session_state.phone = st.text_input("Phone (simulated)", st.session_state.phone)
    if st.button("New farmer number"):
        st.session_state.phone = f"+9198{uuid.uuid4().int % 10**8:08d}"
        st.rerun()
    with st.expander("Danger zone"):
        if st.button("Reset database"):
            init_db(reset=True)
            clock.reset()
            demo.reset_world()
            st.rerun()
    st.caption(f"LLM: {'on' if config.USE_LLM else 'off (rules)'} · Voice: {'Sarvam' if config.SARVAM_API_KEY else 'off'}"
               f" · Live weather: {'on' if config.WEATHER_LIVE else 'off'}")

phone = st.session_state.phone
from app.engine.conversation import phone_hash  # noqa: E402

with session_scope() as db:
    case = db.scalars(select(Case).where(Case.phone_hash == phone_hash(phone)).order_by(Case.id.desc())).first()
    case_id = case.id if case else None

# ---------------------------------------------------------------- layout
left, right = st.columns([5, 6], gap="large")

with left:
    st.subheader("💬 WhatsApp (simulated)")
    chat = st.container(height=560)
    with session_scope() as db:
        msgs = list(db.scalars(select(Message).where(Message.case_id == case_id).order_by(Message.id))) if case_id else []
    with chat:
        if not msgs:
            st.info("Type the farmer's first message below, e.g. “कल शाम ओले गिरे, सरसों खराब हो गई, 3 बीघा”, "
                    "or load a scripted demo from the sidebar.")
        for m in msgs:
            role = "user" if m.direction == "in" else "assistant"
            with st.chat_message(role, avatar="👨‍🌾" if role == "user" else "🌾"):
                st.caption(m.at.strftime("%d %b %H:%M"))
                if m.media_kind == "photo" and m.media_path and Path(m.media_path).exists():
                    st.image(m.media_path, width=220)
                if m.text:
                    st.markdown(m.text.replace("\n", "  \n"))
                if (m.meta or {}).get("transcript"):
                    st.caption("🎙️ " + m.meta["transcript"])
                if m.audio_path and Path(m.audio_path).exists():
                    st.audio(m.audio_path)
                if m.direction == "out" and m.media_path and Path(m.media_path).exists() and m.media_kind == "document":
                    st.download_button("📄 " + Path(m.media_path).name, Path(m.media_path).read_bytes(),
                                       file_name=Path(m.media_path).name, key=f"dl{m.id}")

    txt = st.chat_input("Farmer types / speaks (Hindi or Hinglish)…")
    if txt:
        demo.send(phone, text=txt)
        st.rerun()

    with st.expander("📷 Send a photo / 📍 location / 🎙️ voice"):
        tab_p, tab_l, tab_v = st.tabs(["Photo", "Location", "Voice note"])
        with tab_p:
            method = st.radio("How it arrives", ["Capture page (time + GPS)", "WhatsApp Document (EXIF kept)",
                                                 "WhatsApp photo (EXIF stripped)", "Forwarded image"], index=0)
            vlist = [v["name"] for v in geo.villages()]
            vdefault = vlist.index(case.village) if case and case.village in vlist else 0
            vname = st.selectbox("Taken near village", vlist, index=vdefault)
            v = geo.village(vname)
            off_km = st.slider("Distance from village centre (km)", 0.0, 30.0, 0.3, 0.1)
            up = st.file_uploader("Photo (or leave empty to use a generated sample field photo)", type=["jpg", "jpeg", "png"])
            crop = st.selectbox("Sample photo crop", ["mustard", "wheat", "gram", "barley"])
            if st.button("Send photo"):
                lat, lon = v["lat"] + off_km / 111, v["lon"]
                name = f"ui_{uuid.uuid4().hex[:8]}"
                if up is not None:
                    path = demo.PHOTO_DIR / f"{name}.jpg"
                    Image.open(up).convert("RGB").save(path, "JPEG")
                    path = str(path)
                    exif_kw = {}
                else:
                    exif_kw = {"taken_at": clock.now(), "lat": lat, "lon": lon}
                    path = demo.make_photo(name, crop=crop, **exif_kw)
                if method.startswith("Capture"):
                    demo.send(phone, photo_path=path, via_capture_page=True, lat=lat, lon=lon)
                elif method.startswith("WhatsApp Document"):
                    demo.send(phone, photo_path=path, as_document=True)
                elif method.startswith("WhatsApp photo"):
                    stripped = demo.PHOTO_DIR / f"{name}_wa.jpg"
                    Image.open(path).convert("RGB").resize((480, 360)).save(stripped, "JPEG", quality=60)
                    demo.send(phone, photo_path=str(stripped))
                else:
                    demo.send(phone, photo_path=path, as_document=True, forwarded=True)
                st.rerun()
        with tab_l:
            vname2 = st.selectbox("Live location at village", [v["name"] for v in geo.villages()], key="locv")
            v2 = geo.village(vname2)
            if st.button("Share live location"):
                demo.send(phone, lat=v2["lat"], lon=v2["lon"])
                st.rerun()
        with tab_v:
            audio = st.file_uploader("Voice note (ogg/wav/mp3) — needs SARVAM_API_KEY", type=["ogg", "wav", "mp3", "m4a"])
            if st.button("Send voice note") and audio is not None:
                p = config.RUNTIME_DIR / "inbound" / f"{uuid.uuid4().hex}_{audio.name}"
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(audio.read())
                demo.send(phone, audio_path=str(p), audio_seconds=20)
                st.rerun()

with right:
    if not case_id:
        st.subheader("Case")
        st.caption("No case yet for this number.")
        st.stop()
    with session_scope() as db:
        c = db.get(Case, case_id)
        facts = list(db.scalars(select(Fact).where(Fact.case_id == case_id).order_by(Fact.id)))
        decisions = list(db.scalars(select(Decision).where(Decision.case_id == case_id).order_by(Decision.id)))
        attempts = list(db.scalars(select(ChannelAttempt).where(ChannelAttempt.case_id == case_id).order_by(ChannelAttempt.id)))
        actions = list(db.scalars(select(Action).where(Action.case_id == case_id).order_by(Action.id)))
        evidence = list(db.scalars(select(Evidence).where(Evidence.case_id == case_id).order_by(Evidence.id)))
        checks = list(db.scalars(select(ScheduledCheck).where(ScheduledCheck.case_id == case_id).order_by(ScheduledCheck.due_at)))

    st.subheader(f"Case KS-{c.id:05d} · {c.state}")
    st.caption(STATE_HI.get(c.state, ""))
    left_h = None if not c.deadline_at else (c.deadline_at - clock.now()).total_seconds() / 3600
    cells = [
        ("Claim route", c.claim_type or "—", ""),
        ("Deadline", c.deadline_at.strftime("%d %b %H:%M") if c.deadline_at else "n/a",
         "" if left_h is None else (f"{left_h:.0f} h left" if left_h > 0 else "passed")),
        ("Reference", c.reference_no or "—", "MOCK" if c.reference_no else ""),
        ("Cost so far", f"₹{c.cost_inr:.2f}", "LLM+STT"),
    ]
    for col, (label, val, sub) in zip(st.columns(4), cells):
        col.markdown(f"<div style='font-size:.8rem;opacity:.7'>{label}</div>"
                     f"<div style='font-size:1.05rem;font-weight:600;word-break:break-all'>{val}</div>"
                     f"<div style='font-size:.75rem;opacity:.7'>{sub}</div>", unsafe_allow_html=True)
    if c.outcome:
        txt = f"**Outcome: {c.outcome}**"
        if c.paid_amount:
            txt += f" · paid {hi.rupees(c.paid_amount)} [MOCK]"
        if c.blocker:
            txt += f"  \nBlocker: {c.blocker}  \nNext step: {c.next_step}"
        (st.success if c.outcome == "PAID" else st.warning if c.outcome == "BLOCKED" else st.info)(txt)

    tabs = st.tabs(["🧠 Decisions", "📑 Provenance", "📞 Channel attempts", "✋ Consent", "📷 Evidence", "⏱️ Scheduled"])
    with tabs[0]:
        st.caption("Why the agent did each step (planner trace).")
        for d in reversed(decisions):
            st.markdown(f"`{d.at:%d %b %H:%M}` **{d.chosen_action}** · _{d.state}_  \n{d.reason}")
    with tabs[1]:
        st.caption("Latest value per key. Blue = farmer said · green = record/portal · yellow = fixture · amber = agent estimate.")
        latest = {}
        for f in facts:
            latest[f.key] = f
        df = pd.DataFrame([{"key": f.key, "value": str(f.value), "source": f.source,
                            "confirmed": "✅" if f.confirmed_by_farmer else "",
                            "flags": " ".join(x for x, on in (("MOCK", f.mock), ("illustrative", f.illustrative)) if on),
                            "note": f.note or "", "at": f.retrieved_at.strftime("%d %b %H:%M")} for f in latest.values()])
        if not df.empty:
            st.dataframe(df.style.apply(lambda r: [f"background-color: {SOURCE_COLOURS.get(r['source'], '')}; color: #111"] * len(r), axis=1),
                         use_container_width=True, hide_index=True)
        with st.expander("Full fact history"):
            st.dataframe(pd.DataFrame([{"key": f.key, "value": str(f.value), "source": f.source,
                                        "at": f.retrieved_at} for f in facts]), hide_index=True, use_container_width=True)
    with tabs[2]:
        if attempts:
            st.dataframe(pd.DataFrame([{"channel": a.channel, "label": channels.LABEL_HI.get(a.channel), "at": a.started_at,
                                        "result": a.result, "ref": a.ref_no, "mock": "MOCK", "response": a.raw}
                                       for a in attempts]), hide_index=True, use_container_width=True)
        else:
            st.caption("No reporting attempts yet.")
    with tabs[3]:
        for a in reversed(actions):
            icon = {"EXECUTED": "✅", "PENDING": "⏳", "DECLINED": "🚫", "SUPERSEDED": "↩️", "FAILED": "❌"}.get(a.status, "")
            with st.expander(f"{icon} {a.kind} · {a.status} · {a.created_at:%d %b %H:%M}"):
                st.markdown(a.readback_text_hi.replace("\n", "  \n"))
                st.json({"fields": a.payload.get("fields"), "values": a.payload.get("values"),
                         "confirmed_at": str(a.confirmed_at), "result": a.result})
    with tabs[4]:
        for e in evidence:
            cols = st.columns([1, 3])
            if e.kind == "photo" and e.path and Path(e.path).exists():
                cols[0].image(e.path, width=120)
            elif e.kind == "document" and e.path and Path(e.path).exists():
                cols[0].download_button("📄 PDF", Path(e.path).read_bytes(), file_name=Path(e.path).name, key=f"ev{e.id}")
            else:
                cols[0].write(e.kind)
            cols[1].markdown(f"**{e.title or e.kind}** {'✅ valid' if e.valid else '❌ ' + ', '.join(e.problems or [])}  \n"
                             f"method: {e.capture_method or '-'} · captured: {e.captured_at or '-'} · "
                             f"loc: {f'{e.lat:.4f},{e.lon:.4f}' if e.lat else '-'} · crop seen: {e.crop_detected or '-'}")
    with tabs[5]:
        st.dataframe(pd.DataFrame([{"kind": k.kind, "due": k.due_at, "done": k.done, "note": k.note} for k in checks]),
                     hide_index=True, use_container_width=True)
        if st.button("Run due checks now"):
            scheduler.tick()
            st.rerun()
