"""Information-only baseline: same LLM, no tools, no case record, no follow-up.

It can explain the 72-hour rule but cannot file anything, so reporting completion is 0 by design.
For payability it is asked whether a payout is due; without yield data it can only guess. With the LLM
off, it answers "cannot tell" (counted as wrong), which is what an honest info-bot would do.
"""
from __future__ import annotations

from app import config
from app.nlu import llm

SYSTEM = ("You are an information-only PMFBY crop insurance chatbot. You have no tools and no access to "
          "portals or data. Answer the farmer briefly in Hindi.")


def evaluate(s: dict) -> dict:
    out = {"reported": False, "payable_answer": None}
    if "payable" in s["expect"] and llm.enabled():
        data, _ = llm.call_json(
            config.LLM_INTENT_MODEL, SYSTEM,
            s["opening"] + "\nक्या मुझे क्लेम का पैसा मिलेगा? (Answer yes/no/unknown)",
            llm.obj({"answer": {"type": "string", "enum": ["yes", "no", "unknown"]}}), effort="low")
        out["payable_answer"] = (data or {}).get("answer")
    return out
