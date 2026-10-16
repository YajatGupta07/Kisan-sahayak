"""Tiny key-value store in the DB for global settings (clock offset, fault injection, toggles)."""
from __future__ import annotations

from typing import Any

from app.db import session_scope
from app.models.case import KV


def get(key: str, default: Any = None) -> Any:
    with session_scope() as db:
        row = db.get(KV, key)
        return default if row is None else row.value


def set(key: str, value: Any) -> None:  # noqa: A001
    with session_scope() as db:
        row = db.get(KV, key)
        if row is None:
            db.add(KV(key=key, value=value))
        else:
            row.value = value


def faults() -> dict[str, str]:
    return get("faults", {}) or {}


def set_fault(channel: str, behaviour: str) -> None:
    f = faults()
    f[channel] = behaviour
    set("faults", f)
