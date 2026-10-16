"""Hindi message templates. Facts are grouped by source:
   आपने बताया… (farmer) / रिकॉर्ड में… (portal, record, insurer, bank, weather) / मेरा अंदाज़ा… (estimate).
"""
from __future__ import annotations

from datetime import datetime
from typing import Iterable, Optional

from app.models.case import Fact

CROP_HI = {"mustard": "सरसों", "wheat": "गेहूं", "gram": "चना", "barley": "जौ"}
EVENT_HI = {"hail": "ओलावृष्टि", "inundation": "जलभराव", "natural_fire": "आग/बिजली", "cloudburst": "बादल फटना",
            "unseasonal_rain": "बेमौसम बारिश", "cyclonic_rain": "आंधी-बारिश", "frost": "पाला", "drought": "सूखा",
            "pest": "कीट/रोग", "landslide": "भूस्खलन"}
MONTH_HI = ["जनवरी", "फरवरी", "मार्च", "अप्रैल", "मई", "जून", "जुलाई", "अगस्त", "सितंबर", "अक्टूबर", "नवंबर",
            "दिसंबर"]
KEY_HI = {"event_type": "नुकसान", "event_at": "नुकसान का समय", "crop_reported": "फसल (आपने बताई)",
          "crop_insured": "बीमित फसल", "area_ha": "नुकसान वाला रकबा", "khasra": "खसरा", "village": "गांव",
          "policy_no": "पॉलिसी नंबर", "sum_insured": "बीमा राशि", "weather": "मौसम रिकॉर्ड",
          "deadline_at": "रिपोर्ट की आखिरी समय-सीमा", "reference_no": "रेफरेंस नंबर",
          "assessed_loss_pct": "सर्वे में आंका गया नुकसान", "estimate_inr": "अनुमानित क्लेम",
          "actual_yield": "इकाई की वास्तविक उपज", "threshold_yield": "थ्रेशोल्ड उपज", "payment": "भुगतान"}
RECORD_SOURCES = {"portal", "record", "insurer", "bank", "weather", "land_record", "fixture"}


def crop(c: Optional[str]) -> str:
    return CROP_HI.get(c or "", c or "-")


def event(e: Optional[str]) -> str:
    return EVENT_HI.get(e or "", e or "-")


def when(dt: Optional[datetime]) -> str:
    if not dt:
        return "-"
    h = dt.hour
    part = "सुबह" if 4 <= h < 12 else "दोपहर" if 12 <= h < 16 else "शाम" if 16 <= h < 20 else "रात"
    h12 = h % 12 or 12
    return f"{dt.day} {MONTH_HI[dt.month - 1]} {part} {h12} बजे"


def rupees(x: Optional[float]) -> str:
    if x is None:
        return "-"
    s = f"{int(round(x)):,}"
    return "₹" + s


def area(ha: Optional[float]) -> str:
    if ha is None:
        return "-"
    from app.config import BIGHA_TO_HA
    return f"{ha:.2f} हेक्टेयर (लगभग {ha / BIGHA_TO_HA:.1f} बीघा)"


def hours_left(deadline: Optional[datetime], now: datetime) -> str:
    if not deadline:
        return ""
    h = (deadline - now).total_seconds() / 3600
    if h <= 0:
        return "समय-सीमा निकल चुकी है"
    return f"{int(h)} घंटे बचे हैं"


def render_value(f: Fact) -> str:
    v = f.value
    if f.key in ("crop_reported", "crop_insured"):
        return crop(v)
    if f.key == "event_type":
        return event(v)
    if f.key in ("event_at", "deadline_at") and isinstance(v, str):
        return when(datetime.fromisoformat(v))
    if f.key == "area_ha":
        return area(v)
    if f.key in ("sum_insured", "estimate_inr"):
        return rupees(v)
    return str(v)


def grouped(facts: Iterable[Fact]) -> str:
    farmer, record, est = [], [], []
    for f in facts:
        label = KEY_HI.get(f.key, f.key)
        tag = " [MOCK]" if f.mock else ""
        tag += " [उदाहरण डेटा]" if f.illustrative else ""
        line = f"• {label}: {render_value(f)}{tag}"
        if f.source == "farmer":
            farmer.append(line)
        elif f.source == "agent_estimate":
            est.append(line)
        else:
            record.append(line)
    parts = []
    if farmer:
        parts.append("*आपने बताया:*\n" + "\n".join(farmer))
    if record:
        parts.append("*रिकॉर्ड में:*\n" + "\n".join(record))
    if est:
        parts.append("*मेरा अंदाज़ा (पक्का नहीं):*\n" + "\n".join(est))
    return "\n\n".join(parts)


# ---------- fixed messages ----------
GREETING = ("नमस्ते, मैं साक्षी हूँ — फसल बीमा (PMFBY) में आपकी मदद के लिए। "
            "नुकसान के बारे में बोलकर या लिखकर बताइए: क्या हुआ, कब हुआ, कौन सी फसल।")
ASK_EVENT = "क्या नुकसान हुआ? (जैसे ओले, पानी भरना, बेमौसम बारिश, आग, पाला)"
ASK_TIME = "नुकसान कब हुआ? (जैसे “कल रात”, “परसों शाम”, “12 मार्च”)"
ASK_CROP = "कौन सी फसल का नुकसान हुआ? (सरसों, गेहूं, चना, जौ)"
ASK_AREA = "कितने रकबे में नुकसान हुआ? (बीघा या हेक्टेयर में बताइए)"
ASK_POLICY = ("आपकी बीमा पॉलिसी ढूंढनी है। इनमें से जो हो वो भेजिए:\n"
              "1. बीमा रसीद/पॉलिसी नंबर (जैसे RJ25R000101)\n2. KCC/लोन खाता नंबर")
ASK_OTP = "पोर्टल ने आपके मोबाइल पर OTP भेजा है। कृपया वह OTP यहाँ भेजिए। (मैं OTP कहीं और इस्तेमाल नहीं करूँगा)"
ASK_CORRECTION = "क्या गलत है? सही जानकारी बताइए, मैं ठीक करके फिर से पढ़कर सुनाऊँगा।"
VOICE_FAILED = "आपकी आवाज़ समझ नहीं आई। कृपया दोबारा बोलें या लिखकर भेजें।"
DONT_CLEAR = "ज़रूरी: सर्वे होने तक खेत की फसल न हटाएं, न जलाएं, न जुताई करें।"


def ask_photos(link: str, hours: str) -> str:
    return ("अब खेत की कम से कम 2 फोटो चाहिए — नुकसान साफ दिखे।\n"
            f"सबसे अच्छा तरीका: यह लिंक खोलें और खेत में खड़े होकर फोटो लें (समय और जगह अपने-आप जुड़ जाएगी): {link}\n"
            "या WhatsApp पर फोटो *Document* की तरह भेजें और खेत से *लाइव लोकेशन* शेयर करें।\n"
            f"फोटो न हो तो भी बताइए — रिपोर्ट रुकेगी नहीं। ({hours})")


def deadline_readback(event_type, event_at, deadline_at, crop_reported, assumed_time: bool) -> str:
    extra = "\n(आपने समय नहीं बताया, इसलिए सुरक्षित रहने के लिए सुबह 6 बजे माना है।)" if assumed_time else ""
    return (f"आपके हिसाब से {crop(crop_reported)} में {event(event_type)} का नुकसान {when(event_at)} हुआ।\n"
            f"बीमा कंपनी को बताने की आखिरी समय-सीमा: *{when(deadline_at)}* (72 घंटे)।{extra}\n"
            "क्या यह सही है? *हाँ* या *नहीं* लिखें/बोलें।")


def report_readback(c, channel_hi: str) -> str:
    return ("मैं आपके नाम से यह नुकसान रिपोर्ट दर्ज करने वाला हूँ:\n"
            f"• किसान: {c.farmer_name_masked or '-'}\n"
            f"• पॉलिसी: {c.policy_no}\n"
            f"• नुकसान: {event(c.event_type)}, {when(c.event_at)}\n"
            f"• फसल: {crop(c.crop_insured or c.crop_reported)}\n"
            f"• रकबा: {area(c.area_ha)}\n"
            f"• खेत: {c.village}, खसरा {c.khasra or '-'}\n"
            f"• पहला रास्ता: {channel_hi} (न चले तो अगला रास्ता)\n"
            "[MOCK] बीमा कंपनी का सिस्टम इस डेमो में नकली है।\n"
            "क्या मैं यह रिपोर्ट दर्ज करूँ? *हाँ* या *नहीं*।")


def widespread_note(c) -> str:
    return (f"{event(c.event_type)} जैसा नुकसान आमतौर पर पूरे इलाके में होता है। ऐसे नुकसान में PMFBY का क्लेम "
            "आपकी बीमा इकाई (गांव/पटवार मंडल) की फसल कटाई प्रयोग (CCE) वाली उपज से तय होता है, अलग से सर्वे से नहीं। "
            "मैं आपकी पॉलिसी ढूंढकर केस खुला रखूँगा, और उपज के आंकड़े आने पर बताऊँगा कि क्लेम बनता है या नहीं।")


def grievance_readback(c, reason_hi: str, to_hi: str) -> str:
    return (f"मैं आपके नाम से शिकायत दर्ज करना चाहता हूँ:\n• कहाँ: {to_hi}\n• पॉलिसी: {c.policy_no}\n"
            f"• रेफरेंस: {c.reference_no or '-'}\n• शिकायत: {reason_hi}\n"
            "क्या मैं यह शिकायत दर्ज करूँ? *हाँ* या *नहीं*।")


def rti_readback(c, iu: str, season: str) -> str:
    return (f"आपकी इकाई ({iu}) की {season} की उपज के आंकड़े अभी तक सार्वजनिक नहीं हुए हैं। "
            "मैं आपके नाम से कृषि विभाग, राजस्थान को RTI आवेदन का ड्राफ्ट तैयार कर सकता हूँ (फीस ₹10)। "
            "इसमें इकाई की CCE उपज और थ्रेशोल्ड उपज मांगी जाएगी। क्या मैं ड्राफ्ट बनाऊँ? *हाँ* या *नहीं*।")


def correction_readback(c, insured, sown) -> str:
    return (f"पॉलिसी में फसल *{crop(insured)}* लिखी है, लेकिन आपने/फोटो में *{crop(sown)}* है।\n"
            "इस हालत में क्लेम खारिज हो जाएगा, इसलिए मैं अभी क्लेम दर्ज नहीं कर रहा।\n"
            "यह गलती आमतौर पर बैंक या CSC पर बीमा करते समय होती है।\n"
            "मैं आपके नाम से फसल सुधार (enrolment correction) का अनुरोध तैयार कर सकता हूँ। क्या बनाऊँ? *हाँ* या *नहीं*।")
