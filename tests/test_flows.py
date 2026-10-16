from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from app import clock, demo, kv
from app.db import session_scope
from app.engine import scheduler
from app.models.case import Case, ChannelAttempt, Decision, Evidence, Message
from app.tools import yield_engine

P = "+919822200002"


def _case(db) -> Case:
    return db.scalars(select(Case).order_by(Case.id.desc())).first()


def test_demo1_outage_reaches_helpline_then_paid():
    cid = demo.demo1_hail_app_outage()
    s = demo.case_summary(cid)
    assert s["state"] == "AWAIT_SURVEY" and s["ref"].startswith("KR14447-")
    scheduler.advance_clock(timedelta(days=60))
    s = demo.case_summary(cid)
    assert s["state"] == "CLOSED_PAID" and s["paid"] > 0


def test_demo2_unseeded_account_grievance_blocked():
    cid = demo.demo2_payable_unseeded()
    s = demo.case_summary(cid)
    assert s["state"] == "BLOCKED" and "seeded" in s["blocker"]
    with session_scope() as db:
        first_check = db.scalars(select(Decision).where(Decision.case_id == cid,
                                                        Decision.chosen_action.like("check:%"))).first()
        assert first_check.chosen_action == "check:bank"  # planner chose bank first from the failure signal


def test_demo3_not_payable_with_figures():
    cid = demo.demo3_not_payable()
    s = demo.case_summary(cid)
    assert s["state"] == "CLOSED_NOT_PAYABLE"
    with session_scope() as db:
        last = db.scalars(select(Message).where(Message.case_id == cid).order_by(Message.id.desc())).first()
        assert "थ्रेशोल्ड" in last.text and "किलो" in last.text


def test_all_channels_fail_logs_proof_and_retries():
    for ch in ("insurer_app", "helpline_14447", "insurer_office", "bank_branch", "csc"):
        kv.set_fault(ch, "error_once")
    clock.set_to(datetime(2026, 3, 14, 21, 0))  # Saturday night: offices closed
    demo.send(P, text="कल शाम 6 बजे ओले गिरे, सरसों खराब, 3 बीघा")
    demo.send(P, text="हाँ")
    demo.send(P, text="रसीद RJ25R000101")
    demo.send(P, text="photo nahi hai")
    demo.send(P, text="हाँ")
    with session_scope() as db:
        c = _case(db)
        assert c.reference_no is None and c.state == "REPORTING"
        assert db.scalar(select(Evidence).where(Evidence.title.like("Attempt log%"))) is not None
        assert {d.chosen_action for d in db.scalars(select(Decision))} >= {"skip:bank_branch", "all_channels_failed"}
    scheduler.advance_clock(timedelta(hours=3))
    with session_scope() as db:
        c = _case(db)
        assert c.reference_no and c.reported_at <= c.deadline_at


def test_invalid_reference_is_a_failure():
    kv.set_fault("insurer_app", "invalid_ref")
    demo.send(P, text="कल शाम 6 बजे ओले गिरे, सरसों खराब, 3 बीघा")
    demo.send(P, text="हाँ")
    demo.send(P, text="रसीद RJ25R000101")
    demo.send(P, text="photo nahi hai")
    demo.send(P, text="हाँ")
    with session_scope() as db:
        c = _case(db)
        assert c.report_channel == "helpline_14447"
        results = [a.result for a in db.scalars(select(ChannelAttempt).order_by(ChannelAttempt.id))]
        assert results == ["invalid_ref", "ok"]


def test_reports_without_photos_when_deadline_close():
    clock.set_to(datetime(2026, 3, 15, 9, 0))  # event 12 Mar 18:00 -> 9h left
    demo.send(P, text="12 मार्च शाम 6 बजे ओले गिरे, सरसों खराब, 3 बीघा")
    demo.send(P, text="हाँ")
    demo.send(P, text="रसीद RJ25R000101")
    with session_scope() as db:
        c = _case(db)
        assert c.state == "REPORT_CONSENT"
        assert db.scalars(select(Decision).where(Decision.chosen_action == "report_now_without_full_evidence")).first()


def test_waiting_for_photos_then_report_now_check_fires():
    demo.send(P, text="कल शाम 6 बजे ओले गिरे, सरसों खराब, 3 बीघा")
    demo.send(P, text="हाँ")
    demo.send(P, text="रसीद RJ25R000101")
    with session_scope() as db:
        assert _case(db).state == "GATHER"
    scheduler.advance_clock(timedelta(hours=40))  # crosses deadline - 12h
    with session_scope() as db:
        assert _case(db).state == "REPORT_CONSENT"


def test_photo_problems_and_recovery():
    demo.send(P, text="कल शाम 6 बजे ओले गिरे, सरसों खराब, 3 बीघा")
    demo.send(P, text="हाँ")
    demo.send(P, text="रसीद RJ25R000101")
    now = clock.now()
    dark = demo.make_photo("t_dark", taken_at=now, lat=27.58, lon=76.80, dark=True)
    demo.send(P, photo_path=dark, as_document=True)
    fwd = demo.make_photo("t_fwd", taken_at=now, lat=27.58, lon=76.80)
    demo.send(P, photo_path=fwd, as_document=True, forwarded=True)
    far = demo.make_photo("t_far", taken_at=now, lat=27.9, lon=76.80)
    demo.send(P, photo_path=far, as_document=True)
    # WhatsApp-compressed photo without EXIF, then live location -> becomes valid
    from PIL import Image
    p = demo.make_photo("t_plain", crop="mustard", seed=3)
    Image.open(p).save(p.replace(".jpg", "_noexif.jpg"))
    demo.send(P, photo_path=p.replace(".jpg", "_noexif.jpg"))
    demo.send(P, lat=27.579, lon=76.803)
    with session_scope() as db:
        ev = list(db.scalars(select(Evidence).where(Evidence.kind == "photo").order_by(Evidence.id)))
        assert "too_dark" in ev[0].problems
        assert "forwarded" in ev[1].problems
        assert any(p.startswith("far_from_plot") for p in ev[2].problems)
        assert ev[3].valid  # recovered via live location


def test_loan_account_with_otp_human_in_the_loop():
    demo.send(P, text="कल शाम ओले गिरे, सरसों खराब, 2 बीघा")
    demo.send(P, text="हाँ")
    demo.send(P, text="KCC लोन खाता 41234567890")
    with session_scope() as db:
        assert _case(db).flag("awaiting") == "otp"
    demo.send(P, text="111111")
    with session_scope() as db:
        assert _case(db).policy_no is None
    demo.send(P, text="123456")
    with session_scope() as db:
        assert _case(db).policy_no == "RJ25R000106"


def test_weather_inconsistent_raised_once_and_not_blocking():
    clock.set_to(datetime(2026, 3, 13, 10, 0))
    demo.send(P, text="कल दोपहर ओले गिरे, सरसों खराब, 2 बीघा")
    demo.send(P, text="हाँ")
    demo.send(P, text="रसीद RJ25R000102")  # Laxmangarh: fixture shows clear sky on 12 Mar; crop mustard matches
    with session_scope() as db:
        c = _case(db)
        assert c.flag("weather_done") == "inconsistent"
        assert c.flag("awaiting") in ("weather_reconfirm", "photos")
    demo.send(P, text="हाँ सच में ओले गिरे थे, सिर्फ हमारे खेत के पास")
    demo.send(P, text="photo nahi hai")
    with session_scope() as db:
        c = _case(db)
        assert c.state == "REPORT_CONSENT"
        from app.engine import record
        assert record.latest_fact(db, c, "farmer_restatement") is not None


def test_survey_stall_escalates_with_consent():
    demo.send(P, text="कल शाम 6 बजे ओले गिरे, गेहूं खराब, 2 बीघा")
    demo.send(P, text="हाँ")
    demo.send(P, text="रसीद RJ25R000105")
    demo.send(P, text="photo nahi hai")
    demo.send(P, text="हाँ")
    scheduler.advance_clock(timedelta(days=12))
    with session_scope() as db:
        c = _case(db)
        assert c.state == "AWAIT_SURVEY" and c.pending_action_id
    demo.send(P, text="हाँ")
    scheduler.advance_clock(timedelta(days=60))
    assert demo.case_summary(_case_id())["state"] == "CLOSED_PAID"


def _case_id():
    with session_scope() as db:
        return _case(db).id


def test_yield_formula_hand_calculation():
    hist = [1500, 1600, 1400, 1700, 1550, 1450, 1650]
    ty = yield_engine.threshold_yield(hist, 0.7)
    assert ty == pytest.approx((1700 + 1650 + 1600 + 1550 + 1500) / 5 * 0.7)
    r = yield_engine.compute(ty, 800, 50000)
    assert r["payable"] and r["claim_inr"] == round((ty - 800) / ty * 50000)
    assert not yield_engine.compute(ty, 1200, 50000)["payable"]


def test_unpublished_yield_leads_to_rti_proposal():
    clock.set_to(datetime(2026, 1, 20, 10, 0))
    demo.send(P, text="कल पाला पड़ा, पूरे गांव का गेहूं खराब")
    demo.send(P, text="रसीद RJ25R000107")
    scheduler.advance_clock(datetime(2026, 9, 15) - clock.now())
    with session_scope() as db:
        c = _case(db)
        from app.engine import consent
        a = consent.pending(db, c)
        assert c.state == "AWAIT_YIELD_DATA" and a and a.kind == "RTI"
    demo.send(P, text="हाँ")
    with session_scope() as db:
        assert db.scalar(select(Evidence).where(Evidence.title == "RTI draft")) is not None


def test_subsidy_delay_is_explained_without_grievance():
    clock.set_to(datetime(2025, 1, 20, 10, 0))
    demo.send(P, text="कल पाला पड़ा, सबकी गेहूं की फसल खराब")
    demo.send(P, text="रसीद RJ24R000109")
    scheduler.advance_clock(datetime(2025, 9, 30) - clock.now())
    with session_scope() as db:
        c = _case(db)
        assert c.state == "BLOCKED" and "subsidy" in c.blocker
        assert c.pending_action_id is None


def test_free_question_does_not_change_state():
    demo.send(P, text="कल शाम 6 बजे ओले गिरे, सरसों खराब, 3 बीघा")
    with session_scope() as db:
        before = _case(db).state
    demo.send(P, text="एजेंट को पैसे देने पड़ेंगे क्या?")
    with session_scope() as db:
        assert _case(db).state == before
