"""Checks for "payable but unpaid". The planner chooses the ORDER from the evidence it has."""
from __future__ import annotations

import json
from functools import lru_cache

from app import config


@lru_cache(maxsize=1)
def _subsidy() -> dict:
    return json.loads((config.DATA_DIR / "alwar/subsidy_status.json").read_text())


def check_bank(policy: dict) -> dict:
    b = policy.get("bank") or {}
    if not b.get("aadhaar_seeded") or not b.get("npci_mapped"):
        what = "not Aadhaar-seeded" if not b.get("aadhaar_seeded") else "not NPCI-mapped"
        return {"check": "bank", "found": True, "blocker": f"Bank account {b.get('account_masked')} is {what}",
                "blocker_hi": f"आपका बैंक खाता ({b.get('account_masked')}) आधार से जुड़ा (सीडेड) नहीं है",
                "next_step": f"Visit {b.get('name')} with Aadhaar card and passbook; ask for Aadhaar seeding and NPCI mapping. Then the insurer re-sends the payment.",
                "next_step_hi": f"आधार कार्ड और पासबुक लेकर {b.get('name')} जाएं और खाते में आधार सीडिंग व NPCI मैपिंग करवाएं। उसके बाद बीमा कंपनी दोबारा भुगतान भेजती है।",
                "source": "bank", "mock": True, "grievance": True}
    return {"check": "bank", "found": False, "detail": "account seeded and NPCI-mapped", "source": "bank", "mock": True}


def check_mapping(policy: dict) -> dict:
    if not policy.get("mapped_to_iu", True):
        return {"check": "mapping", "found": True,
                "blocker": f"Policy {policy['policy_no']} is not mapped to insurance unit {policy['iu_code']} on the portal",
                "blocker_hi": f"पोर्टल पर आपकी पॉलिसी आपके बीमा इकाई ({policy['iu_code']}) से नहीं जुड़ी है",
                "next_step": "Grievance to insurer to correct IU mapping; CSC/bank that enrolled to submit corrected khasra/IU.",
                "next_step_hi": "बीमा कंपनी को शिकायत, और जिस CSC/बैंक से बीमा हुआ था वहां से सही खसरा/इकाई की जानकारी भिजवाएं।",
                "source": "portal", "mock": True, "grievance": True}
    return {"check": "mapping", "found": False, "detail": "policy mapped to correct IU", "source": "portal", "mock": True}


def check_subsidy(season: str) -> dict:
    s = _subsidy().get(season, {})
    if s and not (s.get("state_share_released") and s.get("central_share_released")):
        who = "State" if not s.get("state_share_released") else "Central"
        return {"check": "subsidy", "found": True,
                "blocker": f"{who} share of premium subsidy for {season} not yet released (as of {s.get('as_of')})",
                "blocker_hi": f"इस सीज़न का {'राज्य' if who == 'State' else 'केंद्र'} सरकार का प्रीमियम हिस्सा अभी जारी नहीं हुआ है",
                "next_step": "No individual fix. Agent re-checks every 30 days; farmer need not pay any agent.",
                "next_step_hi": "इसमें आपकी तरफ से कुछ करना नहीं है, और किसी एजेंट को पैसे न दें। मैं हर महीने दोबारा जांच करूंगा।",
                "source": "record", "illustrative": s.get("illustrative", True), "grievance": False}
    return {"check": "subsidy", "found": False, "detail": "premium subsidy released", "source": "record"}


def plan_order(status: dict) -> list[tuple[str, str]]:
    """Choose which check to run first, from the status signal. Returns [(check, reason)]."""
    code = (status or {}).get("code") or ""
    ps = (status or {}).get("payment_status")
    if ps == "failed" or "ACCOUNT" in code:
        return [("bank", "payment attempted and failed -> most often an account/Aadhaar seeding problem"),
                ("mapping", "if the account is fine, check the policy-to-IU mapping"),
                ("subsidy", "last: season-level subsidy release")]
    if "NOT_IN_IU" in code or "MAPPING" in code:
        return [("mapping", "status says farmer not in the IU claim list -> policy mapping first"),
                ("bank", "then account seeding"), ("subsidy", "then subsidy release")]
    return [("subsidy", "status pending with no payment attempt -> funds/subsidy release is the common cause"),
            ("mapping", "then policy-to-IU mapping"), ("bank", "then account seeding")]
