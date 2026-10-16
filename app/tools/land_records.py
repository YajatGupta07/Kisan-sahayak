"""Apna Khata (Rajasthan land records) plot check. Fixtures for the demo; the live site needs a captcha,
which would be forwarded to the farmer (never bypassed)."""
from __future__ import annotations

import json
from functools import lru_cache
from typing import Optional

from app import config, kv


@lru_cache(maxsize=1)
def _plots() -> dict:
    return json.loads((config.DATA_DIR / "fixtures/apna_khata.json").read_text())["plots"]


def lookup(village: str, khasra: str) -> Optional[dict]:
    extra = kv.get("extra_plots", {}) or {}
    return extra.get(f"{village}|{khasra}") or _plots().get(f"{village}|{khasra}")


def match(damaged_village: Optional[str], damaged_khasra: Optional[str], policy: dict) -> dict:
    """Is the damaged plot the insured plot?"""
    insured = [(policy["village"], k) for k in policy["khasra"]]
    if not damaged_khasra:
        return {"status": "assumed_insured_plot", "insured": insured, "source": "fixture"}
    v = damaged_village or policy["village"]
    rec = lookup(v, damaged_khasra)
    if (v, damaged_khasra) in insured:
        return {"status": "match", "record": rec, "insured": insured, "source": "fixture"}
    return {"status": "different_plot", "record": rec, "insured": insured, "source": "fixture"}
