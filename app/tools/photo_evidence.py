"""Photo evidence checks: readable, captured after the event, near the plot, not reused, not forwarded,
and (if the LLM is on) the crop/damage visible in it."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

from PIL import ExifTags, Image, ImageStat

from app import config
from app.nlu import llm
from app.tools import geo


@dataclass
class PhotoMeta:
    sha256: str
    readable: bool
    width: int = 0
    height: int = 0
    captured_at: Optional[datetime] = None
    lat: Optional[float] = None
    lon: Optional[float] = None
    exif_ok: bool = False
    problems: list[str] = field(default_factory=list)


def _gps_to_deg(vals, ref) -> Optional[float]:
    try:
        d, m, s = (float(x) for x in vals)
        deg = d + m / 60 + s / 3600
        return -deg if ref in ("S", "W") else deg
    except Exception:
        return None


def read_meta(path: str) -> PhotoMeta:
    data = open(path, "rb").read()
    meta = PhotoMeta(sha256=hashlib.sha256(data).hexdigest(), readable=False)
    try:
        img = Image.open(path)
        img.load()
    except Exception:
        meta.problems.append("unreadable")
        return meta
    meta.readable = True
    meta.width, meta.height = img.size
    if min(img.size) < 200:
        meta.problems.append("too_small")
    try:
        stat = ImageStat.Stat(img.convert("L"))
        if stat.mean[0] < 25:
            meta.problems.append("too_dark")
        elif stat.stddev[0] < 12:
            meta.problems.append("blank_or_blurred")
    except Exception:
        pass
    exif = img.getexif()
    if exif:
        sub = exif.get_ifd(ExifTags.IFD.Exif)
        dt = sub.get(ExifTags.Base.DateTimeOriginal) or exif.get(ExifTags.Base.DateTime)
        if dt:
            try:
                meta.captured_at = datetime.strptime(str(dt), "%Y:%m:%d %H:%M:%S")
                meta.exif_ok = True
            except ValueError:
                pass
        gps = exif.get_ifd(ExifTags.IFD.GPSInfo)
        if gps and 2 in gps and 4 in gps:
            meta.lat = _gps_to_deg(gps[2], gps.get(1, "N"))
            meta.lon = _gps_to_deg(gps[4], gps.get(3, "E"))
    return meta


def vision_check(path: str) -> tuple[Optional[str], Optional[str], float]:
    """(crop, damage, cost_inr). None when the LLM is off or unsure."""
    if not llm.enabled():
        return None, None, 0.0
    schema = llm.obj({
        "crop": {"type": "string", "enum": ["mustard", "wheat", "gram", "barley", "other", "unclear"]},
        "damage": {"type": "string", "enum": ["hail", "waterlogging", "lodging_rain", "frost", "pest", "fire",
                                              "none_visible", "unclear"]},
        "is_field_photo": {"type": "boolean"},
    })
    data, cost = llm.call_json(
        config.LLM_EXTRACT_MODEL,
        "You check crop-loss evidence photos from Alwar, Rajasthan. Identify the crop and visible damage. "
        "Say 'unclear' rather than guessing.",
        [llm.image_block(path), {"type": "text", "text": "Which crop is this and what damage is visible?"}],
        schema, effort="low")
    if not data or not data.get("is_field_photo"):
        return None, None, cost
    crop = data["crop"] if data["crop"] not in ("other", "unclear") else None
    dmg = data["damage"] if data["damage"] not in ("unclear",) else None
    return crop, dmg, cost


def validate(meta: PhotoMeta, *, event_at: Optional[datetime], now: datetime, village: Optional[str],
             capture_method: str, captured_at: Optional[datetime] = None, lat: Optional[float] = None,
             lon: Optional[float] = None, forwarded: Optional[bool] = None, seen_elsewhere: bool = False
             ) -> tuple[bool, list[str], dict]:
    """Returns (valid, problems, resolved{captured_at, lat, lon})."""
    problems = list(meta.problems)
    cap = captured_at or meta.captured_at
    la, lo = (lat, lon) if lat is not None else (meta.lat, meta.lon)
    if forwarded:
        problems.append("forwarded")
    if seen_elsewhere:
        problems.append("reused_photo")
    if cap is None:
        problems.append("no_capture_time")
    else:
        if event_at and cap < event_at - timedelta(hours=1):
            problems.append("taken_before_event")
        if cap > now + timedelta(minutes=10):
            problems.append("time_in_future")
    if la is None or lo is None:
        problems.append("no_location")
    else:
        v = geo.village(village) if village else None
        if v:
            km = geo.haversine_km(la, lo, v["lat"], v["lon"])
            if km > config.PHOTO_MAX_KM:
                problems.append(f"far_from_plot_{km:.0f}km")
    return (not problems), problems, {"captured_at": cap, "lat": la, "lon": lo}


PROBLEM_HI = {
    "unreadable": "फोटो खुल नहीं रही",
    "too_small": "फोटो बहुत छोटी है",
    "too_dark": "फोटो बहुत अंधेरी है — दिन की रोशनी में लें",
    "blank_or_blurred": "फोटो धुंधली है — फोन स्थिर रखकर फसल पास से लें",
    "forwarded": "यह फोटो फॉरवर्ड की हुई है — खेत में खुद ली गई फोटो चाहिए",
    "reused_photo": "यह फोटो पहले किसी और केस में आ चुकी है",
    "no_capture_time": "फोटो में समय की जानकारी नहीं है",
    "taken_before_event": "फोटो नुकसान से पहले की है",
    "time_in_future": "फोटो का समय गलत है",
    "no_location": "फोटो में जगह (लोकेशन) की जानकारी नहीं है",
}


def problem_hi(p: str) -> str:
    if p.startswith("far_from_plot_"):
        return f"फोटो खेत से लगभग {p.split('_')[-1].replace('km', '')} किमी दूर ली गई लगती है"
    return PROBLEM_HI.get(p, p)
