"""Helpers that write to the case record: facts (with provenance), decisions, messages, checks."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import clock
from app.models.case import Case, Decision, Fact, Message, ScheduledCheck

# Case columns that mirror a fact of the same key
_CASE_FIELDS = {
    "event_type", "event_time_text", "event_at", "harvest_at", "deadline_at", "crop_reported", "crop_insured",
    "policy_no", "village", "khasra", "iu_code", "area_ha", "insured_area_ha", "sum_insured", "claim_type",
    "reference_no", "season",
}


def _jsonable(v: Any) -> Any:
    if isinstance(v, datetime):
        return v.isoformat(timespec="minutes")
    return v


def set_fact(db: Session, case: Case, key: str, value: Any, source: str, *, confirmed: bool = False,
             evidence_ref: Optional[str] = None, mock: bool = False, illustrative: bool = False,
             note: Optional[str] = None) -> Fact:
    f = Fact(case_id=case.id, key=key, value=_jsonable(value), source=str(getattr(source, "value", source)),
             confirmed_by_farmer=confirmed, retrieved_at=clock.now(), evidence_ref=evidence_ref,
             mock=mock, illustrative=illustrative, note=note)
    db.add(f)
    if key in _CASE_FIELDS:
        setattr(case, key, value)
    db.flush()
    return f


def latest_fact(db: Session, case: Case, key: str) -> Optional[Fact]:
    return db.scalars(
        select(Fact).where(Fact.case_id == case.id, Fact.key == key).order_by(Fact.id.desc()).limit(1)
    ).first()


def latest_facts(db: Session, case: Case) -> dict[str, Fact]:
    out: dict[str, Fact] = {}
    for f in db.scalars(select(Fact).where(Fact.case_id == case.id).order_by(Fact.id)):
        out[f.key] = f
    return out


def decide(db: Session, case: Case, action: str, reason: str, inputs: Optional[dict] = None) -> Decision:
    d = Decision(case_id=case.id, at=clock.now(), state=case.state, chosen_action=action, reason=reason,
                 inputs={k: _jsonable(v) for k, v in (inputs or {}).items()})
    db.add(d)
    db.flush()
    return d


def say(db: Session, case: Case, text: str, *, ask: Optional[str] = None, audio_path: Optional[str] = None,
        media_path: Optional[str] = None, media_kind: Optional[str] = None, **meta) -> Message:
    m = Message(case_id=case.id, direction="out", at=clock.now(), text=text, audio_path=audio_path,
                media_path=media_path, media_kind=media_kind, meta={"ask": ask, **meta})
    if ask:
        case.set_flag("awaiting", ask)
    db.add(m)
    db.flush()
    return m


def schedule(db: Session, case: Case, kind: str, due_at: datetime, note: str = "", *, replace: bool = True):
    """Schedule a check. With replace=True, an existing undone check of the same kind is moved."""
    kind = str(getattr(kind, "value", kind))
    if replace:
        existing = db.scalars(select(ScheduledCheck).where(
            ScheduledCheck.case_id == case.id, ScheduledCheck.kind == kind, ScheduledCheck.done.is_(False))).all()
        for e in existing:
            e.done = True
            e.note = (e.note or "") + " [replaced]"
    c = ScheduledCheck(case_id=case.id, kind=kind, due_at=due_at, note=note)
    db.add(c)
    db.flush()
    return c


def cancel_checks(db: Session, case: Case, kinds: Optional[list[str]] = None) -> None:
    q = select(ScheduledCheck).where(ScheduledCheck.case_id == case.id, ScheduledCheck.done.is_(False))
    for c in db.scalars(q):
        if kinds is None or c.kind in kinds:
            c.done = True
            c.note = (c.note or "") + " [cancelled]"
