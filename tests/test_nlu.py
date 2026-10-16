from datetime import datetime, timedelta

import pytest

from app.models.enums import Intent
from app.nlu import extract_loss, hindi_dates, intent

NOW = datetime(2026, 3, 13, 19, 30)  # Friday evening
# 30 utterances -> expected event time (deadline = +72h)
CASES = [
    ("kal raat ole gire", datetime(2026, 3, 12, 22)),
    ("कल रात ओले गिरे", datetime(2026, 3, 12, 22)),
    ("कल शाम 6 बजे ओले गिरे", datetime(2026, 3, 12, 18)),
    ("kal shaam ko barish hui", datetime(2026, 3, 12, 18)),
    ("parson subah pani bhar gaya", datetime(2026, 3, 11, 7)),
    ("परसों दोपहर आंधी आई", datetime(2026, 3, 11, 13)),
    ("aaj dopahar ole pade", datetime(2026, 3, 13, 13)),
    ("आज सुबह खेत में पानी भर गया", datetime(2026, 3, 13, 7)),
    ("abhi thodi der pehle ole gire", datetime(2026, 3, 13, 19, 30)),
    ("अभी ओले गिरे", datetime(2026, 3, 13, 19, 30)),
    ("2 din pehle raat ko", datetime(2026, 3, 11, 22)),
    ("do din pehle shaam", datetime(2026, 3, 11, 18)),
    ("तीन दिन पहले सुबह", datetime(2026, 3, 10, 7)),
    ("3 ghante pehle", datetime(2026, 3, 13, 16)),
    ("12 march shaam", datetime(2026, 3, 12, 18)),
    ("12 मार्च रात", datetime(2026, 3, 12, 22)),
    ("11/3 ko subah", datetime(2026, 3, 11, 7)),
    ("budhvar raat", datetime(2026, 3, 11, 22)),
    ("बुधवार शाम को", datetime(2026, 3, 11, 18)),
    ("guruvar ko dopahar", datetime(2026, 3, 12, 13)),
    ("somvar subah", datetime(2026, 3, 9, 7)),
    ("Holi ke din", datetime(2026, 3, 4, 6)),
    ("होली के अगले दिन शाम", datetime(2026, 3, 5, 18)),
    ("kal", datetime(2026, 3, 12, 6)),
    ("कल", datetime(2026, 3, 12, 6)),
    ("parson", datetime(2026, 3, 11, 6)),
    ("kal raat 11 baje", datetime(2026, 3, 12, 23)),
    ("कल शाम 5 बजे", datetime(2026, 3, 12, 17)),
    ("aaj subah 8 baje", datetime(2026, 3, 13, 8)),
    ("१२ मार्च शाम", datetime(2026, 3, 12, 18)),
]


@pytest.mark.parametrize("text,expected", CASES)
def test_dates_resolve(text, expected):
    r = hindi_dates.resolve(text, NOW)
    assert r.at == expected, (text, r)
    assert r.at + timedelta(hours=72) > r.at


def test_no_date_cue_is_ambiguous():
    r = hindi_dates.resolve("fasal kharab ho gayi", NOW)
    assert r.at is None and r.ambiguous


def test_kal_raat_after_midnight_means_night_just_gone():
    r = hindi_dates.resolve("kal raat ole gire", datetime(2026, 3, 13, 2, 0))
    assert r.at == datetime(2026, 3, 12, 22)


def test_extract_basic():
    ev = extract_loss.extract_rules("कल शाम ओले गिरे, मेरी सरसों खराब, 3 बीघा, खसरा 214, रसीद RJ25R000101")
    assert ev.event_type == "hail" and ev.crop == "mustard"
    assert ev.area_ha == pytest.approx(3 * 0.2529, rel=1e-3)
    assert ev.khasra == "214" and ev.receipt_no == "RJ25R000101"
    assert ev.event_time_text


def test_extract_romanised_and_words():
    ev = extract_loss.extract_rules("kal raat pani bhar gaya, gehun ki fasal, dedh bigha")
    assert ev.event_type == "inundation" and ev.crop == "wheat"
    assert ev.area_ha == pytest.approx(1.5 * 0.2529, rel=1e-3)


def test_extract_loan_and_otp():
    assert extract_loss.extract_rules("KCC account 41234567890").loan_account == "41234567890"
    assert extract_loss.extract_rules("123456", awaiting="otp").otp == "123456"


@pytest.mark.parametrize("event,harvested,route", [
    ("hail", None, "LOCALISED"), ("inundation", None, "LOCALISED"), ("unseasonal_rain", True, "POST_HARVEST"),
    ("unseasonal_rain", None, "WIDESPREAD"), ("frost", None, "WIDESPREAD"), ("hail", True, "POST_HARVEST"),
])
def test_claim_route(event, harvested, route):
    assert extract_loss.claim_type_for(event, harvested) == route


@pytest.mark.parametrize("text,new,expected", [
    ("हाँ", False, Intent.CONFIRM), ("haan ji sahi hai", False, Intent.CONFIRM), ("ok", False, Intent.CONFIRM),
    ("नहीं", False, Intent.DENY), ("mat karo", False, Intent.DENY), ("galat hai", False, Intent.DENY),
    ("नहीं, 2 बीघा है", True, Intent.CORRECTION), ("haan lekin 2 nahi 3 bigha", True, Intent.CORRECTION),
    ("survey kab hoga?", False, Intent.QUESTION), ("हाँ, पैसा कब आएगा?", False, Intent.QUESTION),
    ("नाना जी के खेत में", False, Intent.INFO),
])
def test_intent(text, new, expected):
    assert intent.classify_rules(text, new) == expected
