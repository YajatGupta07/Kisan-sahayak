"""Safety core: no executor is reachable without a confirmed Action; nothing unconfirmed goes out."""
import pytest
from sqlalchemy import select

from app import demo
from app.db import session_scope
from app.engine import consent, record
from app.models.case import Action, Case, ChannelAttempt
from app.models.enums import ActionStatus

P = "+919811100001"


def _to_report_readback():
    demo.send(P, text="कल शाम 6 बजे ओले गिरे, सरसों खराब, 3 बीघा")
    demo.send(P, text="हाँ")
    demo.send(P, text="रसीद RJ25R000101")
    demo.send(P, text="photo nahi hai")


def _case(db) -> Case:
    return db.scalars(select(Case).order_by(Case.id.desc())).first()


def test_report_waits_for_explicit_yes():
    _to_report_readback()
    with session_scope() as db:
        c = _case(db)
        a = consent.pending(db, c)
        assert a is not None and a.kind == "REPORT_LOSS"
        assert db.scalar(select(ChannelAttempt).where(ChannelAttempt.case_id == c.id)) is None
    demo.send(P, text="survey kab hoga?")  # a question is not consent
    with session_scope() as db:
        assert db.scalar(select(ChannelAttempt)) is None
    demo.send(P, text="हाँ")
    with session_scope() as db:
        c = _case(db)
        assert c.reference_no and db.scalar(select(ChannelAttempt)) is not None


def test_no_means_nothing_filed_and_asks_correction():
    _to_report_readback()
    demo.send(P, text="नहीं")
    with session_scope() as db:
        c = _case(db)
        assert c.reference_no is None
        assert db.scalar(select(ChannelAttempt)) is None
        assert c.flag("awaiting") == "correction"


def test_correction_regenerates_readback_with_new_area():
    _to_report_readback()
    demo.send(P, text="नहीं, 2 बीघा में नुकसान है")
    with session_scope() as db:
        c = _case(db)
        a = consent.pending(db, c)
        assert a.kind == "REPORT_LOSS"
        assert a.payload["values"]["area_ha"] == pytest.approx(2 * 0.2529, rel=1e-3)
        assert db.scalar(select(ChannelAttempt)) is None


def test_executor_refuses_unconfirmed_action():
    _to_report_readback()
    with session_scope() as db:
        c = _case(db)
        a = consent.pending(db, c)
        with pytest.raises(consent.ConsentError):
            consent._execute(db, c, a)  # PENDING
        a.status = ActionStatus.CONFIRMED.value
        a.confirmation_message_id = a.readback_message_id  # not after the read-back
        with pytest.raises(consent.ConsentError):
            consent._execute(db, c, a)


def test_executor_refuses_field_changed_after_readback():
    _to_report_readback()
    with session_scope() as db:
        c = _case(db)
        a = consent.pending(db, c)
        for k in a.payload["fields"]:
            record.latest_fact(db, c, k).confirmed_by_farmer = True
        record.set_fact(db, c, "area_ha", 5.0, "farmer", confirmed=True)  # sneaky change
        a.status = ActionStatus.CONFIRMED.value
        a.confirmation_message_id = a.readback_message_id + 1
        with pytest.raises(consent.ConsentError, match="changed"):
            consent._execute(db, c, a)


def test_all_payload_fields_marked_confirmed_after_yes():
    _to_report_readback()
    demo.send(P, text="हाँ")
    with session_scope() as db:
        c = _case(db)
        a = db.scalars(select(Action).where(Action.kind == "REPORT_LOSS")).first()
        assert a.status == "EXECUTED"
        for k in a.payload["fields"]:
            assert record.latest_fact(db, c, k).confirmed_by_farmer, k


def test_crop_mismatch_stops_before_filing():
    demo.send(P, text="कल शाम ओले गिरे, मेरे चने की फसल खराब, 2 बीघा")
    demo.send(P, text="हाँ")
    demo.send(P, text="रसीद RJ25R000102")  # policy says mustard
    with session_scope() as db:
        c = _case(db)
        assert c.state == "CROP_MISMATCH"
        assert consent.pending(db, c).kind == "ENROLMENT_CORRECTION"
        assert db.scalar(select(ChannelAttempt)) is None
    demo.send(P, text="हाँ")
    with session_scope() as db:
        c = _case(db)
        assert c.state == "BLOCKED" and "differs" in c.blocker
        assert db.scalar(select(ChannelAttempt)) is None
