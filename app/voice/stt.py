"""Speech-to-text via Sarvam AI (Saarika). Returns None when unavailable; the agent then asks for text.

Verify the endpoint/field names against the current Sarvam docs before the demo.
"""
from __future__ import annotations

import logging
from typing import Optional

import httpx

from app import config

log = logging.getLogger(__name__)
URL = "https://api.sarvam.ai/speech-to-text"


def transcribe(path: str, mime: str = "audio/ogg") -> Optional[str]:
    if not config.SARVAM_API_KEY:
        return None
    try:
        with open(path, "rb") as f:
            r = httpx.post(URL, headers={"api-subscription-key": config.SARVAM_API_KEY},
                           files={"file": (path.rsplit("/", 1)[-1], f, mime)},
                           data={"model": config.SARVAM_STT_MODEL, "language_code": "hi-IN"}, timeout=60)
        r.raise_for_status()
        return (r.json().get("transcript") or "").strip() or None
    except Exception as e:
        log.warning("STT failed: %s", e)
        return None
