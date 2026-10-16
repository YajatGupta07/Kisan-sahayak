"""Classify a farmer reply: CONFIRM / DENY / CORRECTION / QUESTION / INFO."""
from __future__ import annotations

from app import config
from app.models.enums import Intent
from app.nlu import llm
from app.nlu.text import has_any, norm

YES = ["haan", "han", "haa", "haanji", "ji haan", "sahi", "sahee", "theek", "thik", "ok", "okay", "yes",
       "bilkul", "kar do", "kardo", "karo", "confirm", "हाँ", "हां", "हा", "जी हाँ", "सही", "ठीक", "बिल्कुल", "कर दो",
       "करो", "👍"]
NO = ["nahi", "nahin", "nai", "mat", "galat", "no", "ruko", "rukiye", "नहीं", "नही", "ना", "मत", "गलत",
      "रुको", "रुकिए"]
QUESTION = ["kya", "kyon", "kyu", "kaise", "kab", "kitna", "kitne", "kaun", "kahan", "batao", "bataiye",
            "क्या", "क्यों", "कैसे", "कब", "कितना", "कितने", "कौन", "कहाँ", "कहां", "बताओ", "बताइए"]


def classify_rules(text: str, has_new_info: bool = False) -> Intent:
    t = norm(text)
    if not t:
        return Intent.INFO
    yes, no = has_any(t, YES, whole=True), has_any(t, NO, whole=True)
    # Safety: any "no" wins over "yes" ("mat karo", "haan... nahi").
    if no:
        return Intent.CORRECTION if has_new_info else Intent.DENY
    if "?" in t or has_any(t, QUESTION, whole=True):
        return Intent.QUESTION
    if yes:
        # has_new_info means values that DIFFER from what was read back
        return Intent.CORRECTION if has_new_info else Intent.CONFIRM
    return Intent.INFO


_SCHEMA = llm.obj({"intent": {"type": "string", "enum": [i.value for i in Intent]}})
_SYSTEM = (
    "Classify a farmer's WhatsApp reply (Hindi / romanised Hindi) to an agent that just read back a summary "
    "and asked for confirmation. CONFIRM = clear yes to the read-back. DENY = no, without new details. "
    "CORRECTION = says something is wrong and gives the right value. QUESTION = asks something. "
    "INFO = provides information without confirming or denying. When unsure between CONFIRM and anything "
    "else, do not choose CONFIRM."
)


def classify(text: str, *, has_new_info: bool = False, after_readback: bool = False) -> tuple[Intent, float]:
    rule = classify_rules(text, has_new_info)
    if not after_readback or not llm.enabled():
        return rule, 0.0
    data, cost = llm.call_json(config.LLM_INTENT_MODEL, _SYSTEM, text, _SCHEMA, effort="low", max_tokens=1000)
    if not data:
        return rule, cost
    got = Intent(data["intent"])
    # Consent safety: CONFIRM only if both the rules and the model agree.
    if got == Intent.CONFIRM and rule != Intent.CONFIRM:
        return rule, cost
    if rule == Intent.CONFIRM and got != Intent.CONFIRM:
        return got, cost
    return got, cost
