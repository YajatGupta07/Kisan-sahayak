"""Real or simulated clock. All times are naive IST.

The simulated clock is real time plus an offset stored in the DB (so the API server and the
dashboard share it). Tests/eval can freeze time with `freeze()`.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))
_frozen: datetime | None = None


def real_now() -> datetime:
    return datetime.now(IST).replace(tzinfo=None, microsecond=0)


def _get_offset() -> float:
    from app import kv
    return float(kv.get("clock_offset_s", 0.0))


def now() -> datetime:
    if _frozen is not None:
        return _frozen
    return real_now() + timedelta(seconds=_get_offset())


def freeze(at: datetime | None) -> None:
    """Freeze time (eval/tests). Pass None to unfreeze."""
    global _frozen
    _frozen = at


def is_frozen() -> bool:
    return _frozen is not None


def set_to(at: datetime) -> None:
    global _frozen
    if _frozen is not None:
        _frozen = at
        return
    from app import kv
    kv.set("clock_offset_s", (at - real_now()).total_seconds())


def advance(delta: timedelta) -> datetime:
    set_to(now() + delta)
    return now()


def reset() -> None:
    from app import kv
    kv.set("clock_offset_s", 0.0)
