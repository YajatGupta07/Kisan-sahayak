"""Insurance units, villages and distances (data/alwar/insurance_units.json)."""
from __future__ import annotations

import json
import math
from functools import lru_cache
from typing import Optional

from app import config


@lru_cache(maxsize=1)
def _units() -> dict:
    return json.loads((config.DATA_DIR / "alwar/insurance_units.json").read_text())


def villages() -> list[dict]:
    out = []
    for u in _units()["units"]:
        for v in u["villages"]:
            out.append({**v, "iu_code": u["iu_code"], "tehsil": u["tehsil"]})
    return out


def find_village(text_norm: str) -> Optional[dict]:
    # longest names first so "Kishangarh Bas" beats shorter matches
    for v in sorted(villages(), key=lambda v: -len(v["name"])):
        if v["name"].lower() in text_norm or v["name_hi"] in text_norm:
            return v
    return None


def village(name: Optional[str]) -> Optional[dict]:
    if not name:
        return None
    for v in villages():
        if v["name"].lower() == name.lower():
            return v
    return None


def iu_for_village(name: str) -> Optional[str]:
    v = village(name)
    return v["iu_code"] if v else None


def haversine_km(lat1, lon1, lat2, lon2) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))
