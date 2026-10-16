"""Thin Claude wrapper for the narrow LLM jobs (extraction, intent, free questions, photo check).

Every caller has a rule-based fallback, so any failure here (no key, network, refusal, bad JSON)
returns None and the agent carries on deterministically.
"""
from __future__ import annotations

import base64
import json
import logging
from typing import Any, Optional

from app import config

log = logging.getLogger(__name__)
_client = None


def enabled() -> bool:
    return config.USE_LLM


def _get_client():
    global _client
    if _client is None:
        import anthropic
        _client = anthropic.Anthropic()
    return _client


def _cost_inr(model: str, usage) -> float:
    pin, pout = config.LLM_PRICE_PER_MTOK.get(model, (4.0, 20.0))
    usd = (usage.input_tokens * pin + usage.output_tokens * pout) / 1_000_000
    return usd * config.USD_TO_INR


def call_json(model: str, system: str, content: Any, schema: dict, *, effort: str = "low",
              max_tokens: int = 4000) -> tuple[Optional[dict], float]:
    """Structured-output call. Returns (parsed_json | None, cost_inr)."""
    if not enabled():
        return None, 0.0
    import anthropic
    try:
        resp = _get_client().messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": content}],
            output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
        )
    except (anthropic.APIStatusError, anthropic.APIConnectionError) as e:
        log.warning("LLM call failed, using rules: %s", e)
        return None, 0.0
    cost = _cost_inr(model, resp.usage)
    if resp.stop_reason in ("refusal", "max_tokens"):
        log.warning("LLM stop_reason=%s, using rules", resp.stop_reason)
        return None, cost
    text = next((b.text for b in resp.content if b.type == "text"), None)
    try:
        return (json.loads(text) if text else None), cost
    except json.JSONDecodeError:
        return None, cost


def call_text(model: str, system: str, content: Any, *, effort: str = "low",
              max_tokens: int = 2000) -> tuple[Optional[str], float]:
    if not enabled():
        return None, 0.0
    import anthropic
    try:
        resp = _get_client().messages.create(
            model=model, max_tokens=max_tokens, system=system,
            messages=[{"role": "user", "content": content}],
            output_config={"effort": effort},
        )
    except (anthropic.APIStatusError, anthropic.APIConnectionError) as e:
        log.warning("LLM call failed: %s", e)
        return None, 0.0
    cost = _cost_inr(model, resp.usage)
    if resp.stop_reason == "refusal":
        return None, cost
    return "".join(b.text for b in resp.content if b.type == "text") or None, cost


def image_block(path: str, media_type: str = "image/jpeg") -> dict:
    with open(path, "rb") as f:
        data = base64.standard_b64encode(f.read()).decode("utf-8")
    return {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": data}}


def obj(props: dict, required: Optional[list] = None) -> dict:
    """JSON schema object helper (strict: all listed, no extras)."""
    return {"type": "object", "properties": props, "required": required or list(props), "additionalProperties": False}
