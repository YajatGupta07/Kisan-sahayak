"""Policy lookup by receipt/policy no. or loan account (fixtures; source label `fixture`, `mock`).

Real portal lookups sit behind OTP/captcha. That step is modelled here: lookups by loan account can
return `needs_otp`, and the agent forwards the OTP prompt to the farmer and waits.
"""
from __future__ import annotations

import json
from functools import lru_cache
from typing import Optional

from app import config, kv

DEMO_OTP = "123456"  # the mock portal accepts this OTP


@lru_cache(maxsize=1)
def _fixtures() -> list[dict]:
    return json.loads((config.DATA_DIR / "fixtures/policies.json").read_text())["policies"]


def all_policies() -> list[dict]:
    """Fixture policies plus any injected by the eval/dashboard (kv 'extra_policies')."""
    return _fixtures() + list((kv.get("extra_policies", {}) or {}).values())


def _apply_toggles(p: dict) -> dict:
    p = dict(p)
    if kv.get("force_crop_mismatch", False):
        p["crop"] = {"mustard": "gram", "gram": "mustard", "wheat": "barley", "barley": "wheat"}[p["crop"]]
        p["_toggle"] = "crop-mismatch toggle on"
    return p


def by_receipt(receipt_no: str) -> dict:
    for p in all_policies():
        if p["receipt_no"].upper() == receipt_no.upper() or p["policy_no"].upper() == receipt_no.upper():
            return {"status": "found", "policy": _apply_toggles(p), "via": "receipt", "mock": True}
    return {"status": "not_found", "via": "receipt", "mock": True}


def by_loan_account(account: str, otp: Optional[str] = None) -> dict:
    for p in all_policies():
        if p.get("loan_account") and p["loan_account"] == account:
            if p.get("otp_required") and otp is None:
                return {"status": "needs_otp", "via": "loan_account", "mock": True}
            if p.get("otp_required") and otp != DEMO_OTP:
                return {"status": "otp_wrong", "via": "loan_account", "mock": True}
            return {"status": "found", "policy": _apply_toggles(p), "via": "loan_account", "mock": True}
    return {"status": "not_found", "via": "loan_account", "mock": True}
