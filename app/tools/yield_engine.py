"""Area-based (widespread loss) payability under PMFBY.

    Threshold yield (TY) = mean of best 5 of last 7 years' yields x indemnity level
    Shortfall            = (TY - Actual) / TY   if Actual < TY else 0
    Claim                = Shortfall x Sum insured
"""
from __future__ import annotations

import json
from datetime import date, datetime
from functools import lru_cache
from typing import Optional

from app import config


@lru_cache(maxsize=1)
def _data() -> dict:
    return json.loads((config.DATA_DIR / "alwar/yields.json").read_text())


def season_for(dt: datetime) -> str:
    y = dt.year
    if dt.month >= 10:
        return f"rabi_{y}_{(y + 1) % 100:02d}"
    if dt.month <= 4:
        return f"rabi_{y - 1}_{y % 100:02d}"
    return f"kharif_{y}"


def season_info(season: str) -> Optional[dict]:
    return _data()["seasons"].get(season)


def threshold_yield(history: list[float], indemnity: float) -> float:
    best5 = sorted(history, reverse=True)[:5]
    return sum(best5) / len(best5) * indemnity


def compute(threshold: float, actual: float, sum_insured: float) -> dict:
    shortfall = max(0.0, (threshold - actual) / threshold) if threshold else 0.0
    return {"shortfall": round(shortfall, 4), "claim_inr": round(shortfall * sum_insured), "payable": shortfall > 0}


def evaluate(iu_code: str, crop: str, season: str, sum_insured: float, today: date) -> dict:
    d = _data()
    info = d["seasons"].get(season)
    row = next((r for r in d["rows"] if r["iu_code"] == iu_code and r["crop"] == crop and r["season"] == season),
               None)
    out = {"iu_code": iu_code, "crop": crop, "season": season,
           "expected_publish": info and info["expected_publish"], "published": False}
    if not info or not row:
        out["reason"] = "no data row for this IU/crop/season"
        return out
    published_on = date.fromisoformat(info["published_on"]) if info.get("published_on") else None
    if row["actual_kg_ha"] is None or published_on is None or today < published_on:
        out["reason"] = "yield data not yet published" if row["actual_kg_ha"] is not None else "not published"
        out["never_published"] = row["actual_kg_ha"] is None
        return out
    indemnity = d["indemnity_level"][crop]
    ty = threshold_yield(row["history_kg_ha"], indemnity)
    res = compute(ty, row["actual_kg_ha"], sum_insured)
    out.update({
        "published": True, "published_on": info["published_on"], "actual_kg_ha": row["actual_kg_ha"],
        "threshold_kg_ha": round(ty), "history_kg_ha": row["history_kg_ha"], "indemnity_level": indemnity,
        "sum_insured": sum_insured, **res,
        "source_url": row.get("source_url"), "illustrative": row.get("illustrative", False),
    })
    return out
