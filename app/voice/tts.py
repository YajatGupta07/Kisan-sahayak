"""Text-to-speech via Sarvam AI (Bulbul) for read-backs. Returns a WAV path, or None if unavailable.

Verify the endpoint/field names against the current Sarvam docs before the demo.
"""
from __future__ import annotations

import base64
import logging
import re
from typing import Optional

import httpx

from app import config

log = logging.getLogger(__name__)
URL = "https://api.sarvam.ai/text-to-speech"
AUDIO_DIR = config.RUNTIME_DIR / "audio"


def _speakable(text: str) -> str:
    t = re.sub(r"[*_•]", " ", text)
    t = re.sub(r"\[MOCK\][^\n]*", "", t)
    return re.sub(r"\s+", " ", t).strip()


def synthesize(text: str, name: str) -> Optional[str]:
    if not config.SARVAM_API_KEY:
        return None
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    try:
        r = httpx.post(URL, headers={"api-subscription-key": config.SARVAM_API_KEY},
                       json={"text": _speakable(text)[:1500], "target_language_code": "hi-IN",
                             "speaker": config.SARVAM_TTS_SPEAKER, "model": config.SARVAM_TTS_MODEL}, timeout=60)
        r.raise_for_status()
        audio_b64 = r.json()["audios"][0]
        path = AUDIO_DIR / f"{name}.wav"
        path.write_bytes(base64.b64decode(audio_b64))
        return str(path)
    except Exception as e:
        log.warning("TTS failed: %s", e)
        return None
