"""Resolve loosely described loss timing ("kal raat", "परसों शाम", "Holi ke din") to a datetime.

Resolution is relative to the message time (IST). The loss is always in the past, so "kal" means
yesterday. If the text is ambiguous or has no time cue, `resolve` returns `None` with a reason so
the agent asks a follow-up instead of guessing.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional

from app.nlu.text import has_any, norm, parse_number

PART_OF_DAY = [  # (words, hour)
    (["subah", "savere", "sawere", "सुबह", "सवेरे", "morning"], 7),
    (["dopahar", "dopehar", "दोपहर", "afternoon", "noon"], 13),
    (["shaam", "sham", "शाम", "evening"], 18),
    (["raat", "rat", "रात", "night"], 22),
]

WEEKDAYS = [  # Monday=0
    ["somvar", "somwar", "सोमवार", "monday"],
    ["mangalvar", "mangalwar", "मंगलवार", "tuesday"],
    ["budhvar", "budhwar", "बुधवार", "wednesday"],
    ["guruvar", "guruwar", "brihaspativar", "गुरुवार", "बृहस्पतिवार", "thursday"],
    ["shukravar", "shukrawar", "शुक्रवार", "friday"],
    ["shanivar", "shaniwar", "शनिवार", "saturday"],
    ["ravivar", "raviwar", "itvaar", "रविवार", "इतवार", "sunday"],
]

MONTHS = {
    "jan": 1, "january": 1, "जनवरी": 1, "feb": 2, "february": 2, "फरवरी": 2, "march": 3, "mar": 3, "मार्च": 3,
    "april": 4, "apr": 4, "अप्रैल": 4, "may": 5, "मई": 5, "june": 6, "जून": 6, "july": 7, "जुलाई": 7,
    "aug": 8, "august": 8, "अगस्त": 8, "sep": 9, "september": 9, "सितंबर": 9, "oct": 10, "october": 10,
    "अक्टूबर": 10, "nov": 11, "november": 11, "नवंबर": 11, "dec": 12, "december": 12, "दिसंबर": 12,
}

# Festival dates relevant to the Rabi season (approximate public-holiday dates; extend as needed).
FESTIVALS = {
    "holi": {2023: date(2023, 3, 8), 2024: date(2024, 3, 25), 2025: date(2025, 3, 14), 2026: date(2026, 3, 4),
             2027: date(2027, 3, 22)},
    "होली": "holi",
    "dhulandi": "holi", "धुलंडी": "holi",
    "shivratri": {2024: date(2024, 3, 8), 2025: date(2025, 2, 26), 2026: date(2026, 2, 15)},
    "शिवरात्रि": "shivratri",
    "basant panchami": {2025: date(2025, 2, 2), 2026: date(2026, 1, 23)},
    "बसंत पंचमी": "basant panchami",
    "gangaur": {2025: date(2025, 3, 31), 2026: date(2026, 3, 21)},
    "गणगौर": "gangaur",
}


@dataclass
class Resolved:
    at: Optional[datetime]
    reason: str           # how it was resolved, or why not
    ambiguous: bool = False
    has_time_of_day: bool = False


def _part_of_day(t: str) -> Optional[int]:
    part = None
    for words, hour in PART_OF_DAY:
        if has_any(t, words):
            part = hour
            break
    m = re.search(r"(\d{1,2})\s*(?:baje|बजे|bje|o'?clock)", t)
    if m:
        h = int(m.group(1))
        if part in (13, 18, 22) and h < 12 and not (part == 22 and h <= 4):
            h += 12
        return h % 24
    return part


def _festival(t: str, now: datetime) -> Optional[date]:
    for name, val in FESTIVALS.items():
        if name in t:
            table = FESTIVALS[val] if isinstance(val, str) else val
            cands = [d for y, d in table.items() if isinstance(y, int) and d and d <= now.date()]
            if cands:
                return max(cands)
    return None


def resolve(text: str, now: datetime) -> Resolved:
    t = norm(text)
    hour = _part_of_day(t)
    day: Optional[date] = None
    how = ""

    # "N din pehle" / "N दिन पहले"
    m = re.search(r"(\S+)\s*(?:din|दिन)\s*(?:pehle|pahle|पहले|purv|पूर्व)", t)
    if m and parse_number(m.group(1)) is not None:
        n = int(parse_number(m.group(1)))
        day, how = now.date() - timedelta(days=n), f"{n} din pehle"
    # "N ghante pehle"
    m = re.search(r"(\S+)\s*(?:ghante|ghanta|घंटे|घंटा)\s*(?:pehle|pahle|पहले)", t)
    if m and parse_number(m.group(1)) is not None:
        at = now - timedelta(hours=parse_number(m.group(1)))
        return Resolved(at.replace(minute=0, second=0), f"{m.group(1)} ghante pehle", has_time_of_day=True)

    if day is None:
        # explicit date: "12 march", "12 मार्च", "12/3"
        m = re.search(r"(\d{1,2})\s*(?:tarikh|तारीख)?\s*([a-zऀ-ॿ]+)", t)
        if m and m.group(2) in MONTHS:
            d, mo = int(m.group(1)), MONTHS[m.group(2)]
            y = now.year if (mo, d) <= (now.month, now.day) else now.year - 1
            try:
                day, how = date(y, mo, d), "explicit date"
            except ValueError:
                pass
        m2 = re.search(r"\b(\d{1,2})[/\-.](\d{1,2})(?:[/\-.](\d{2,4}))?\b", t)
        if day is None and m2:
            d, mo = int(m2.group(1)), int(m2.group(2))
            y = int(m2.group(3)) if m2.group(3) else now.year
            y = y + 2000 if y < 100 else y
            try:
                day, how = date(y, mo, d), "explicit date"
                if day > now.date():
                    day = date(y - 1, mo, d)
            except ValueError:
                day = None

    if day is None:
        if has_any(t, ["parson", "parso", "परसों", "परसो"]):
            day, how = now.date() - timedelta(days=2), "parson"
        elif has_any(t, ["kal", "कल", "yesterday"]):
            day, how = now.date() - timedelta(days=1), "kal"
        elif has_any(t, ["aaj", "aj", "आज", "today", "abhi", "अभी", "thodi der pehle", "थोड़ी देर पहले"]):
            day, how = now.date(), "aaj"
            if has_any(t, ["abhi", "अभी", "thodi der", "थोड़ी देर"]) and hour is None:
                return Resolved(now.replace(second=0), "abhi", has_time_of_day=True)
        else:
            for i, words in enumerate(WEEKDAYS):
                if has_any(t, words):
                    back = (now.weekday() - i) % 7 or 7  # most recent past occurrence, not today
                    if has_any(t, ["pichhle", "pichle", "पिछले"]) and back < 7:
                        back += 7
                    day, how = now.date() - timedelta(days=back), f"weekday {words[0]}"
                    break
    if day is None:
        fd = _festival(t, now)
        if fd:
            day, how = fd, "festival"
            if has_any(t, ["agle din", "अगले दिन"]):
                day += timedelta(days=1)

    if day is None:
        if hour is not None:
            # Only a time of day: assume the most recent such time
            at = now.replace(hour=hour, minute=0, second=0)
            if at > now:
                at -= timedelta(days=1)
            return Resolved(at, "time of day only; assumed most recent", ambiguous=True, has_time_of_day=True)
        return Resolved(None, "no date cue found", ambiguous=True)

    # "kal raat" said after midnight but before morning usually means the night just gone
    if how == "kal" and hour == 22 and now.hour < 5:
        day = now.date() - timedelta(days=1)

    # Day known but no time: assume early morning. That gives the earliest (safest) deadline,
    # and the read-back tells the farmer this assumption.
    at = datetime.combine(day, datetime.min.time()).replace(hour=hour if hour is not None else 6)
    if at > now:
        if how == "aaj" and hour is None:
            at = now.replace(second=0)
        elif how == "aaj":  # "aaj shaam" said in the afternoon -> can't be future
            return Resolved(None, "time is in the future", ambiguous=True)
        else:
            at -= timedelta(days=1)
    return Resolved(at, how, has_time_of_day=hour is not None)
