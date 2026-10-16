"""Weather corroboration via the Open-Meteo historical archive (free, no key).

Outputs only consistent / inconsistent / inconclusive. Hail is not reliably visible in reanalysis
data, so a dry record never "disproves" hail on its own; it is raised with the farmer.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Optional

import httpx

from app import config
from app.tools import geo

ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"


def _live(lat: float, lon: float, d0: date, d1: date) -> Optional[dict[str, dict]]:
    params = {
        "latitude": lat, "longitude": lon, "start_date": d0.isoformat(), "end_date": d1.isoformat(),
        "daily": "precipitation_sum,weather_code,wind_gusts_10m_max,temperature_2m_min,temperature_2m_max",
        "timezone": "Asia/Kolkata",
    }
    r = httpx.get(ARCHIVE, params=params, timeout=config.WEATHER_TIMEOUT_S)
    r.raise_for_status()
    d = r.json()["daily"]
    out = {}
    for i, day in enumerate(d["time"]):
        out[day] = {"precip_mm": d["precipitation_sum"][i], "weather_code": d["weather_code"][i],
                    "wind_gust_kmh": d["wind_gusts_10m_max"][i], "tmin_c": d["temperature_2m_min"][i],
                    "tmax_c": d["temperature_2m_max"][i]}
    return out


def _fixture(village: str, d0: date, d1: date) -> dict[str, dict]:
    days = json.loads((config.DATA_DIR / "alwar/weather_fixtures.json").read_text())["days"]
    out = {}
    d = d0
    while d <= d1:
        k = f"{village}|{d.isoformat()}"
        if k in days:
            out[d.isoformat()] = days[k]
        d += timedelta(days=1)
    return out


def classify(event_type: str, days: dict[str, dict]) -> tuple[str, str]:
    if not days:
        return "inconclusive", "no weather record for these dates"
    vals = [v for v in days.values() if v.get("precip_mm") is not None]
    if not vals:
        return "inconclusive", "weather record incomplete"
    precip = max(v["precip_mm"] or 0 for v in vals)
    total = sum(v["precip_mm"] or 0 for v in vals)
    codes = {v.get("weather_code") for v in vals}
    gust = max(v.get("wind_gust_kmh") or 0 for v in vals)
    tmin = min(v.get("tmin_c") if v.get("tmin_c") is not None else 99 for v in vals)
    summary = f"max rain {precip:.1f} mm/day, max gust {gust:.0f} km/h, min temp {tmin:.1f} C"
    if event_type == "hail":
        if codes & {96, 99} or (precip >= 5 and gust >= 40):
            return "consistent", f"thunderstorm recorded ({summary})"
        if total < 0.2 and max(c or 0 for c in codes) < 50:
            return "inconsistent", f"no rain or storm recorded ({summary})"
        return "inconclusive", summary
    if event_type in ("unseasonal_rain", "cyclonic_rain", "cloudburst"):
        if precip >= 2.5:
            return "consistent", f"rain recorded ({summary})"
        if total < 0.2:
            return "inconsistent", f"no rain recorded ({summary})"
        return "inconclusive", summary
    if event_type == "inundation":
        if total >= 30:
            return "consistent", f"heavy rain recorded ({summary})"
        if total < 0.2:
            return "inconsistent", f"no rain recorded ({summary}); waterlogging may still come from canal/neighbouring fields"
        return "inconclusive", summary
    if event_type == "frost":
        if tmin <= 2:
            return "consistent", f"near-freezing night recorded ({summary})"
        if tmin >= 6:
            return "inconsistent", f"no frost-level cold recorded ({summary})"
        return "inconclusive", summary
    return "inconclusive", f"weather does not settle this event type ({summary})"


def corroborate(village: str, event_type: str, event_at: datetime) -> dict:
    v = geo.village(village)
    d0, d1 = (event_at - timedelta(days=1)).date(), (event_at + timedelta(days=1)).date()
    days, source = None, "weather"
    if v and config.WEATHER_LIVE:
        try:
            days = _live(v["lat"], v["lon"], d0, d1)
            source_note = "Open-Meteo historical archive"
        except Exception as e:  # network/timeout -> recorded fixtures
            days = None
            source_note = f"Open-Meteo unavailable ({type(e).__name__})"
    else:
        source_note = "live weather disabled" if v else "village unknown"
    if not days:
        days = _fixture(village or "", d0, d1)
        if days:
            source, source_note = "fixture", source_note + "; used recorded fixture"
    verdict, why = classify(event_type, days or {})
    return {"verdict": verdict, "why": why, "days": days or {}, "source": source, "source_note": source_note}
