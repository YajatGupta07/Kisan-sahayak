"""Answers to free questions. State is never changed here."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app import clock, config
from app.engine import record
from app.models.case import Case
from app.nlu import llm
from app.nlu.text import has_any, norm
from app.responses import hi

STATE_HI = {
    "NEW": "नया केस", "INTAKE": "नुकसान की जानकारी ली जा रही है", "DEADLINE_CONFIRM": "समय-सीमा की पुष्टि बाकी",
    "GATHER": "पॉलिसी/फोटो/जानकारी जुटाई जा रही है", "CROP_MISMATCH": "पॉलिसी में फसल गलत दर्ज है",
    "REPORT_CONSENT": "रिपोर्ट दर्ज करने के लिए आपकी हाँ का इंतज़ार", "REPORTING": "रिपोर्ट दर्ज की जा रही है",
    "REPORTED": "रिपोर्ट दर्ज", "DEADLINE_MISSED_WITH_PROOF": "समय-सीमा निकल गई, कोशिशों का सबूत रखा है",
    "AWAIT_SURVEY": "सर्वे का इंतज़ार", "AWAIT_ASSESSMENT": "नुकसान आकलन का इंतज़ार",
    "AWAIT_YIELD_DATA": "इकाई की उपज के आंकड़ों का इंतज़ार", "AWAIT_PAYMENT": "भुगतान का इंतज़ार",
    "DIAGNOSE": "भुगतान रुकने का कारण जांचा जा रहा है", "CLOSED_PAID": "भुगतान हो गया — केस बंद",
    "CLOSED_NOT_PAYABLE": "क्लेम नहीं बनता — केस बंद", "BLOCKED": "रुकावट मिली है",
}


def status_line(case: Case) -> str:
    s = f"केस KS-{case.id:05d}: {STATE_HI.get(case.state, case.state)}।"
    if case.reference_no:
        s += f" रेफरेंस: {case.reference_no}।"
    if case.blocker:
        s += f" रुकावट: {case.blocker}।"
    return s


def answer(db: Session, case: Case, text: str) -> str:
    t = norm(text)
    now = clock.now()
    if has_any(t, ["deadline", "kab tak", "समय-सीमा", "कब तक", "72", "kitna time", "कितना समय"]):
        if case.deadline_at:
            return f"रिपोर्ट की आखिरी समय-सीमा {hi.when(case.deadline_at)} है — {hi.hours_left(case.deadline_at, now)}।"
        return "ओले, जलभराव, आग जैसे स्थानीय नुकसान की सूचना 72 घंटे के अंदर देनी होती है।"
    if has_any(t, ["kitna paisa", "kitna milega", "कितना पैसा", "कितना मिलेगा", "claim kitna", "क्लेम कितना"]):
        f = record.latest_fact(db, case, "estimate_inr")
        if f:
            return hi.grouped([f]) + "\nयह अंदाज़ा है; असली रकम बीमा कंपनी तय करती है।"
        return ("अभी रकम बताना जल्दी है। स्थानीय नुकसान में रकम = सर्वे में आंका गया नुकसान % × बीमा राशि; "
                "पूरे इलाके के नुकसान में = इकाई की उपज की कमी % × बीमा राशि।")
    if has_any(t, ["survey", "सर्वे", "surveyor", "सर्वेयर"]):
        return "सूचना के बाद 72 घंटे में सर्वेयर नियुक्त होता है और 10 दिन में आकलन पूरा होना चाहिए। " + hi.DONT_CLEAR
    if has_any(t, ["status", "स्टेटस", "kya hua", "क्या हुआ", "kahan tak", "कहाँ तक"]):
        return status_line(case)
    if has_any(t, ["agent", "एजेंट", "dalal", "दलाल"]):
        return "क्लेम के लिए किसी एजेंट को पैसे देने की ज़रूरत नहीं है। PMFBY का क्लेम सीधे आपके खाते में आता है।"
    if llm.enabled():
        facts = record.latest_facts(db, case)
        ctx = "; ".join(f"{k}={f.value} (source {f.source})" for k, f in facts.items())
        out, cost = llm.call_text(
            config.LLM_INTENT_MODEL,
            "You are Saakshi, a PMFBY crop-insurance helper for farmers in Alwar, Rajasthan. Answer in simple "
            "Hindi (Devanagari), max 3 sentences. Use only the case facts given and general PMFBY rules; if "
            "unsure, say so and suggest helpline 14447. Clearly say when something is your estimate.",
            f"Case state: {case.state}. Facts: {ctx}\n\nFarmer asks: {text}")
        case.cost_inr += cost
        if out:
            return "(सामान्य जानकारी) " + out.strip()
    return "मैं इसका पक्का जवाब नहीं दे सकता। आप कृषि रक्षक हेल्पलाइन 14447 पर भी पूछ सकते हैं। " + status_line(case)
