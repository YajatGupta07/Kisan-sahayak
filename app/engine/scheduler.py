"""Durable scheduled checks (DB table) driven by app.clock — so a clock jump fires them in order."""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select

from app import clock
from app.db import session_scope
from app.models.case import Case, ScheduledCheck

MAX_ITER = 2000


def _next_due(until: datetime):
    with session_scope() as db:
        c = db.scalars(select(ScheduledCheck).where(ScheduledCheck.done.is_(False), ScheduledCheck.due_at <= until)
                       .order_by(ScheduledCheck.due_at, ScheduledCheck.id).limit(1)).first()
        return (c.id, c.due_at) if c else None


def _run_one(check_id: int) -> None:
    from app.channels import dispatch
    from app.engine import planner
    with session_scope() as db:
        c = db.get(ScheduledCheck, check_id)
        if c is None or c.done:
            return
        c.done = True
        c.attempts += 1
        case = db.get(Case, c.case_id)
        if case is not None:
            planner.on_check(db, case, c)
    dispatch.flush()


def tick() -> int:
    """Run every check due now. Returns how many ran."""
    n = 0
    for _ in range(MAX_ITER):
        nxt = _next_due(clock.now())
        if not nxt:
            break
        _run_one(nxt[0])
        n += 1
    return n


def advance_clock(delta: timedelta) -> int:
    """Move the (simulated) clock forward, firing due checks at their own due times, in order."""
    target = clock.now() + delta
    n = 0
    for _ in range(MAX_ITER):
        nxt = _next_due(target)
        if not nxt:
            break
        cid, due = nxt
        if due > clock.now():
            clock.set_to(due)
        _run_one(cid)
        n += 1
    clock.set_to(target)
    return n


def pending_checks(case_id: int | None = None) -> list[ScheduledCheck]:
    with session_scope() as db:
        q = select(ScheduledCheck).where(ScheduledCheck.done.is_(False)).order_by(ScheduledCheck.due_at)
        if case_id:
            q = q.where(ScheduledCheck.case_id == case_id)
        return list(db.scalars(q))
