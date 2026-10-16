"""Farmer message -> structured LossEvent fields.

Rules always run (they are the fallback and they catch identifiers reliably). If the LLM is enabled
it fills/overrides the descriptive fields (event type, crop, timing phrase, area) from the same text.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Optional

from app import config
from app.nlu import llm
from app.nlu.text import has_any, norm, parse_number
from app.tools import geo

EVENT_WORDS = {
    "hail": ["ola", "ole", "olay", "olavrishti", "ओला", "ओले", "ओलावृष्टि", "hail", "hailstorm", "gade", "गड़े", "गडे"],
    "inundation": ["paani bhar", "pani bhar", "jal bharav", "jalbharav", "पानी भर", "जलभराव", "बाढ़", "baadh",
                   "waterlogging", "flood", "doob", "डूब"],
    "natural_fire": ["aag", "आग", "bijli", "बिजली", "fire", "lightning"],
    "cloudburst": ["badal fat", "बादल फट", "cloudburst"],
    "unseasonal_rain": ["barish", "baarish", "barsaat", "बारिश", "बरसात", "मावठ", "mavath", "rain", "बेमौसम"],
    "cyclonic_rain": ["aandhi", "andhi", "toofan", "tufan", "आंधी", "आँधी", "तूफान", "storm"],
    "frost": ["pala", "paala", "पाला", "frost", "sheet lehar", "शीतलहर"],
    "drought": ["sukha", "sookha", "सूखा", "drought"],
    "pest": ["keet", "keeda", "कीट", "कीड़ा", "mahu", "माहू", "pest", "rog", "रोग"],
}
LOCALISED_EVENTS = {"hail", "inundation", "natural_fire", "cloudburst", "landslide"}
POST_HARVEST_EVENTS = {"hail", "unseasonal_rain", "cyclonic_rain"}

CROP_WORDS = {
    "mustard": ["sarson", "sarso", "सरसों", "सरसो", "mustard", "rai", "राई"],
    "wheat": ["gehun", "gehu", "gehoon", "गेहूं", "गेहूँ", "गेहू", "wheat"],
    "gram": ["chana", "channa", "चना", "चने", "gram", "chickpea"],
    "barley": ["jau", "जौ", "barley"],
}
HARVESTED_WORDS = ["kat", "kaat", "kati", "kaati", "katai", "काट", "कटी", "कटाई", "कट कर", "kaat kar", "harvest",
                   "khet mein padi", "खेत में पड़ी", "ढेरी", "dheri"]
WIDESPREAD_WORDS = ["pure gaon", "poore gaon", "pura gaon", "पूरे गांव", "पूरे गाँव", "sabki", "sab ki", "सबकी",
                    "सब की", "puri tehsil", "पूरी तहसील", "har khet", "हर खेत"]
TIME_CUES = ["kal", "aaj", "parson", "raat", "shaam", "subah", "dopahar", "din pehle", "din pahle", "baje", "abhi",
             "कल", "आज", "परसों", "रात", "शाम", "सुबह", "दोपहर", "दिन पहले", "बजे", "अभी", "holi", "होली",
             "somvar", "mangalvar", "budhvar", "guruvar", "shukravar", "shanivar", "ravivar", "सोमवार", "मंगलवार",
             "बुधवार", "गुरुवार", "शुक्रवार", "शनिवार", "रविवार", "ghante", "घंटे", "तारीख", "tarikh"]


@dataclass
class LossEvent:
    event_type: Optional[str] = None
    event_time_text: Optional[str] = None
    crop: Optional[str] = None
    area_ha: Optional[float] = None
    area_text: Optional[str] = None
    khasra: Optional[str] = None
    village: Optional[str] = None
    harvested: Optional[bool] = None
    widespread: Optional[bool] = None
    receipt_no: Optional[str] = None
    loan_account: Optional[str] = None
    otp: Optional[str] = None
    no_photos: Optional[bool] = None

    def fields(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v is not None}


def _event_type(t: str) -> Optional[str]:
    for et, words in EVENT_WORDS.items():
        if has_any(t, words):
            return et
    return None


def _crop(t: str) -> Optional[str]:
    for crop, words in CROP_WORDS.items():
        if has_any(t, words):
            return crop
    return None


_AREA_RE = re.compile(r"(\d+(?:\.\d+)?|[a-z\u0900-\u097F]+)\s*(bigha|beegha|बीघा|बीघे|hectares|hectare|हेक्टेयर|ha|"
                      r"acres|acre|एकड़)(?![a-z\u0900-\u097F])")


def _area(t: str) -> tuple[Optional[float], Optional[str]]:
    for m in _AREA_RE.finditer(t):
        n = parse_number(m.group(1))
        if n is None:
            continue
        unit = m.group(2)
        if unit in ("bigha", "beegha", "बीघा", "बीघे"):
            return round(n * config.BIGHA_TO_HA, 3), f"{m.group(1)} bigha"
        if unit in ("acre", "acres", "एकड़"):
            return round(n * 0.4047, 3), f"{m.group(1)} acre"
        return round(n, 3), f"{m.group(1)} hectare"
    return None, None


def _time_text(raw: str, t: str) -> Optional[str]:
    if has_any(t, TIME_CUES) or re.search(r"\d{1,2}\s*(?:[a-zऀ-ॿ]+)", t) and any(
            mo in t for mo in ["march", "मार्च", "feb", "फरवरी", "april", "अप्रैल", "jan", "जनवरी"]):
        return raw.strip()[:200]
    return None


def extract_rules(text: str, *, awaiting: Optional[str] = None) -> LossEvent:
    t = norm(text)
    ev = LossEvent()
    ev.event_type = _event_type(t)
    ev.crop = _crop(t)
    ev.area_ha, ev.area_text = _area(t)
    ev.event_time_text = _time_text(text, t)
    if has_any(t, HARVESTED_WORDS):
        ev.harvested = True
    if has_any(t, WIDESPREAD_WORDS):
        ev.widespread = True
    if has_any(t, ["photo nahi", "photo nahin", "फोटो नहीं", "फ़ोटो नहीं", "no photo", "camera nahi", "कैमरा नहीं"]):
        ev.no_photos = True

    m = re.search(r"(?:khasra|khasara|खसरा)\D{0,6}(\d+(?:/\d+)?)", t)
    if m:
        ev.khasra = m.group(1)
    v = geo.find_village(t)
    if v:
        ev.village = v["name"]

    up = (text or "").upper().translate(str.maketrans("०१२३४५६७८९", "0123456789"))
    m = re.search(r"\b(RJ\d{2}[A-Z]\d{6})\b", up.replace("-", "").replace(" ", "")) or \
        re.search(r"\b(RJ\d{2}[A-Z]\d{6})\b", up)
    if m:
        ev.receipt_no = m.group(1)
    m = re.search(r"(?:LOAN|KCC|लोन|केसीसी|खाता|ACCOUNT|A/C)\D{0,20}(\d{9,18})", up)
    if m:
        ev.loan_account = m.group(1)
    elif awaiting in ("policy_id", "loan_account"):
        m = re.search(r"\b(\d{9,18})\b", up)
        if m:
            ev.loan_account = m.group(1)
    if awaiting == "otp":
        m = re.search(r"\b(\d{4,6})\b", up)
        if m:
            ev.otp = m.group(1)
    if awaiting == "area" and ev.area_ha is None:
        m = re.search(r"^\s*(\d+(?:\.\d+)?)\s*$", t)
        if m:  # bare number in answer to "kitne bigha?" -> bigha
            n = float(m.group(1))
            ev.area_ha, ev.area_text = round(n * config.BIGHA_TO_HA, 3), f"{m.group(1)} bigha"
    if awaiting == "event_time" and ev.event_time_text is None and t:
        ev.event_time_text = text.strip()[:200]
    return ev


_NULLABLE_STR = {"anyOf": [{"type": "string"}, {"type": "null"}]}
_SCHEMA = llm.obj({
    "event_type": {"anyOf": [{"type": "string", "enum": sorted(EVENT_WORDS) + ["landslide"]}, {"type": "null"}]},
    "event_time_text": _NULLABLE_STR,
    "crop": {"anyOf": [{"type": "string", "enum": sorted(CROP_WORDS) + ["other"]}, {"type": "null"}]},
    "area_value": {"anyOf": [{"type": "number"}, {"type": "null"}]},
    "area_unit": {"anyOf": [{"type": "string", "enum": ["bigha", "hectare", "acre"]}, {"type": "null"}]},
    "harvested": {"anyOf": [{"type": "boolean"}, {"type": "null"}]},
    "widespread": {"anyOf": [{"type": "boolean"}, {"type": "null"}]},
})
_SYSTEM = (
    "You extract crop-loss details from a farmer's WhatsApp message in Hindi, Rajasthani/Mewati or romanised "
    "Hindi (Alwar district, Rajasthan). Return only what the farmer actually said; use null for anything not "
    "stated. event_time_text: copy the farmer's own words about WHEN the damage happened (e.g. 'kal raat', "
    "'परसों शाम'), do not convert to a date. harvested: true only if the crop was already cut and lying in "
    "the field. widespread: true only if they say the whole village/area was affected."
)


def extract(text: str, *, awaiting: Optional[str] = None) -> tuple[LossEvent, float]:
    """Returns (event, llm_cost_inr)."""
    ev = extract_rules(text, awaiting=awaiting)
    if not llm.enabled() or not text or len(text.strip()) < 6:
        return ev, 0.0
    data, cost = llm.call_json(config.LLM_EXTRACT_MODEL, _SYSTEM, text, _SCHEMA, effort="low")
    if data:
        ev.event_type = data.get("event_type") or ev.event_type
        crop = data.get("crop")
        ev.crop = crop if crop and crop != "other" else ev.crop
        ev.event_time_text = data.get("event_time_text") or ev.event_time_text
        if data.get("area_value") and ev.area_ha is None:
            unit = data.get("area_unit") or "bigha"
            factor = {"bigha": config.BIGHA_TO_HA, "acre": 0.4047, "hectare": 1.0}[unit]
            ev.area_ha = round(float(data["area_value"]) * factor, 3)
            ev.area_text = f"{data['area_value']} {unit}"
        ev.harvested = data.get("harvested") if data.get("harvested") is not None else ev.harvested
        ev.widespread = data.get("widespread") if data.get("widespread") is not None else ev.widespread
    return ev, cost


def claim_type_for(event_type: Optional[str], harvested: Optional[bool]) -> Optional[str]:
    """PMFBY route: localised calamity (individual survey), post-harvest (individual), or area-based."""
    if not event_type:
        return None
    if harvested and event_type in POST_HARVEST_EVENTS:
        return "POST_HARVEST"
    if event_type in LOCALISED_EVENTS:
        return "LOCALISED"
    return "WIDESPREAD"
