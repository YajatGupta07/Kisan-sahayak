"""MOCK loss-intimation channels with injectable faults.

Writing a loss report into an insurer's system is not available to us, so every channel here is a
labelled mock (`mock=True`) with realistic success and failure responses. Fault behaviour per
channel comes from kv 'faults': ok | error | timeout | no_answer | invalid_ref, optionally with
suffix `_once` (fail the first attempt, then succeed).
"""
from __future__ import annotations

import json
import random
import re
from dataclasses import dataclass
from datetime import datetime, time
from typing import Optional

from app import config, kv
from app.models.enums import Channel

REF_PATTERNS = {
    Channel.INSURER_APP.value: r"^CIA-\d{4}-\d{6}$",
    Channel.HELPLINE.value: r"^KR14447-\d{8}$",
    Channel.INSURER_OFFICE.value: r"^ALW-IO-\d{5}$",
    Channel.BANK_BRANCH.value: r"^BNK-INT-\d{6}$",
    Channel.CSC.value: r"^CSC-\d{10}$",
}
LABEL_HI = {
    Channel.INSURER_APP.value: "क्रॉप इंश्योरेंस ऐप",
    Channel.HELPLINE.value: "कृषि रक्षक हेल्पलाइन 14447",
    Channel.INSURER_OFFICE.value: "बीमा कंपनी का जिला ऑफिस",
    Channel.BANK_BRANCH.value: "बैंक शाखा",
    Channel.CSC.value: "CSC (ई-मित्र/जन सेवा केंद्र)",
}
ALWAYS_OPEN = {Channel.INSURER_APP.value, Channel.HELPLINE.value}


@dataclass
class AttemptResult:
    channel: str
    result: str  # ok | error | timeout | no_answer | invalid_ref
    ref_no: Optional[str]
    raw: str
    mock: bool = True


def _office_hours() -> dict:
    return json.loads((config.DATA_DIR / "alwar/contacts.json").read_text())["office_hours"]


def is_open(channel: str, at: datetime) -> bool:
    if channel in ALWAYS_OPEN:
        return True
    oh = _office_hours()
    if at.weekday() in oh["closed_weekdays"] or at.date().isoformat() in oh["holidays"]:
        return False
    o, c = (time.fromisoformat(oh["open"]), time.fromisoformat(oh["close"]))
    return o <= at.time() < c


def next_open(channel: str, after: datetime) -> datetime:
    from datetime import timedelta
    t = after.replace(minute=0, second=0) + timedelta(hours=1)
    for _ in range(24 * 10):
        if is_open(channel, t):
            return t
        t += timedelta(hours=1)
    return t


def _make_ref(channel: str, rng: random.Random) -> str:
    n = rng.randint(0, 10**10)
    return {
        Channel.INSURER_APP.value: f"CIA-2026-{n % 10**6:06d}",
        Channel.HELPLINE.value: f"KR14447-{n % 10**8:08d}",
        Channel.INSURER_OFFICE.value: f"ALW-IO-{n % 10**5:05d}",
        Channel.BANK_BRANCH.value: f"BNK-INT-{n % 10**6:06d}",
        Channel.CSC.value: f"CSC-{n:010d}",
    }[channel]


def valid_ref(channel: str, ref: Optional[str]) -> bool:
    return bool(ref and re.match(REF_PATTERNS[channel], ref))


def attempt(channel: str, payload: dict, *, attempt_no: int, seed: int = 0) -> AttemptResult:
    behaviour = kv.faults().get(channel, "ok")
    if behaviour.endswith("_once"):
        behaviour = behaviour[:-5] if attempt_no == 1 else "ok"
    rng = random.Random(f"{seed}-{channel}-{attempt_no}")
    if behaviour == "error":
        return AttemptResult(channel, "error", None, "HTTP 503 Service Unavailable (mock)")
    if behaviour == "timeout":
        return AttemptResult(channel, "timeout", None, "no response in 30 s (mock)")
    if behaviour == "no_answer":
        return AttemptResult(channel, "no_answer", None, "call not answered / IVR dropped (mock)")
    if behaviour == "invalid_ref":
        return AttemptResult(channel, "invalid_ref", "REF-???", "submitted, but reference number malformed (mock)")
    ref = _make_ref(channel, rng)
    return AttemptResult(channel, "ok", ref, json.dumps({"status": "registered", "ref": ref, "mock": True}))
