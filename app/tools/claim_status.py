"""MOCK claim-status feed (survey / assessment / payment), driven by each policy's `claim_timeline`
fixture and the simulated clock, so time jumps move the claim forward."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional


def _at(base: Optional[datetime], days) -> Optional[datetime]:
    return None if base is None or days is None else base + timedelta(days=days)


def get(policy: dict, *, claim_type: str, reported_at: Optional[datetime], payable_at: Optional[datetime],
        estimate_inr: Optional[float], now: datetime, grievances: dict[str, datetime]) -> dict:
    tl = policy.get("claim_timeline") or {}
    out: dict = {"mock": True, "survey": None, "assessed_loss_pct": None, "payment_status": "not_due",
                 "events": []}

    if claim_type in ("LOCALISED", "POST_HARVEST"):
        survey_at = _at(reported_at, tl.get("survey_day"))
        if survey_at is None and "survey" in grievances and tl.get("survey_after_grievance_day") is not None:
            survey_at = grievances["survey"] + timedelta(days=tl["survey_after_grievance_day"])
        if survey_at and now >= survey_at:
            out["survey"] = "done"
            out["events"].append(("survey_done", survey_at))
            gap = max(1, (tl.get("assessment_day") or 3) - (tl.get("survey_day") or 0))
            assessed_at = survey_at + timedelta(days=gap)
            if now >= assessed_at:
                out["assessed_loss_pct"] = tl.get("loss_pct")
                out["assessed_at"] = assessed_at
                out["events"].append(("assessed", assessed_at))
                payable_at = assessed_at
        else:
            out["survey"] = "pending"

    pay = tl.get("payment") or {}
    if payable_at and now >= payable_at:
        due = payable_at + timedelta(days=pay.get("day", 30))
        resolved_at = None
        if "payment" in grievances and pay.get("resolves_after_grievance_days") is not None:
            resolved_at = grievances["payment"] + timedelta(days=pay["resolves_after_grievance_days"])
        mode = pay.get("mode", "paid")
        if resolved_at and now >= resolved_at:
            mode = "paid"
            due = resolved_at
        if now < due:
            out["payment_status"] = "processing"
            out["events"].append(("processing", payable_at))
        elif mode == "paid":
            out["payment_status"] = "paid"
            out["paid_amount"] = estimate_inr
            out["paid_on"] = due
            out["events"].append(("paid", due))
        else:
            out["payment_status"] = mode  # failed | pending
            out["code"] = pay.get("code")
            out["events"].append((mode, due))
    out["last_changed"] = max((e[1] for e in out["events"]), default=reported_at)
    return out
