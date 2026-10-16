"""Consent gate: the ONLY path to executors.

    propose()  -> Action(PENDING) + Hindi read-back (text + voice) sent to the farmer
    on_reply() -> CONFIRM on a message *after* the read-back -> CONFIRMED -> _execute()
    _execute() -> refuses unless confirmed, confirmation came after the read-back, and every field in
                  the payload is a farmer-confirmed fact whose value has not changed since the read-back.

The LLM never calls an executor; executors are registered here and are private to this module.
"""
from __future__ import annotations

from typing import Callable, Optional

from sqlalchemy.orm import Session

from app import clock
from app.engine import record
from app.models.case import Action, Case, Message
from app.models.enums import ActionStatus, Intent
from app.voice import tts


class ConsentError(Exception):
    pass


_EXECUTORS: dict[str, Callable[[Session, Case, Action], dict]] = {}


def executor(kind: str):
    def deco(fn):
        _EXECUTORS[kind] = fn
        return fn
    return deco


def pending(db: Session, case: Case) -> Optional[Action]:
    if not case.pending_action_id:
        return None
    a = db.get(Action, case.pending_action_id)
    return a if a and a.status == ActionStatus.PENDING.value else None


def propose(db: Session, case: Case, kind: str, readback_hi: str, fields: list[str], extra: Optional[dict] = None,
            reason: str = "") -> Action:
    old = pending(db, case)
    if old:
        old.status = ActionStatus.SUPERSEDED.value
    values = {}
    for k in fields:
        f = record.latest_fact(db, case, k)
        values[k] = f.value if f else None
    a = Action(case_id=case.id, kind=kind, payload={"fields": fields, "values": values, "from_state": case.state,
                                                     **(extra or {})},
               readback_text_hi=readback_hi, status=ActionStatus.PENDING.value, created_at=clock.now())
    db.add(a)
    db.flush()
    audio = tts.synthesize(readback_hi, name=f"case{case.id}_action{a.id}")
    a.readback_audio = audio
    msg = record.say(db, case, readback_hi, ask="confirm", audio_path=audio, action_id=a.id, action_kind=kind)
    a.readback_message_id = msg.id
    case.pending_action_id = a.id
    record.decide(db, case, f"propose:{kind}", reason or "consequential action needs explicit consent",
                  {"fields": fields})
    return a


def on_reply(db: Session, case: Case, msg: Message, intent: Intent) -> str:
    """Returns 'executed' | 'declined' | 'correction' | 'none'."""
    a = pending(db, case)
    if a is None:
        return "none"
    if intent == Intent.CONFIRM and msg.id > (a.readback_message_id or 0):
        a.status = ActionStatus.CONFIRMED.value
        a.confirmed_at = clock.now()
        a.confirmation_message_id = msg.id
        for k in a.payload.get("fields", []):
            f = record.latest_fact(db, case, k)
            if f is not None:
                f.confirmed_by_farmer = True
        case.pending_action_id = None
        _execute(db, case, a)
        return "executed"
    if intent == Intent.DENY:
        a.status = ActionStatus.DECLINED.value
        case.pending_action_id = None
        record.decide(db, case, f"declined:{a.kind}", "farmer said no to the read-back; nothing submitted")
        return "declined"
    if intent == Intent.CORRECTION:
        a.status = ActionStatus.SUPERSEDED.value
        case.pending_action_id = None
        record.decide(db, case, f"correction:{a.kind}", "farmer corrected a value; read-back will be regenerated")
        return "correction"
    return "none"


def _execute(db: Session, case: Case, a: Action) -> dict:
    if a.status != ActionStatus.CONFIRMED.value:
        raise ConsentError(f"action {a.id} is {a.status}, not CONFIRMED")
    if not a.confirmation_message_id or a.confirmation_message_id <= (a.readback_message_id or 0):
        raise ConsentError("confirmation must come after the read-back")
    for k in a.payload.get("fields", []):
        f = record.latest_fact(db, case, k)
        if f is None or not f.confirmed_by_farmer:
            raise ConsentError(f"field '{k}' not confirmed by farmer")
        if f.value != a.payload["values"].get(k):
            raise ConsentError(f"field '{k}' changed after the read-back")
    fn = _EXECUTORS.get(a.kind)
    if fn is None:
        raise ConsentError(f"no executor for {a.kind}")
    try:
        result = fn(db, case, a)
        a.status = ActionStatus.EXECUTED.value
        a.result = result
        return result
    except ConsentError:
        raise
    except Exception as e:  # executor failure is recorded, not hidden
        a.status = ActionStatus.FAILED.value
        a.result = {"error": repr(e)}
        record.decide(db, case, f"failed:{a.kind}", repr(e))
        raise
