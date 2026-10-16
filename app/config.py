"""Settings, read from environment variables (see .env.example)."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
RUNTIME_DIR = DATA_DIR / "runtime"
RUNTIME_DIR.mkdir(parents=True, exist_ok=True)


def _bool(name: str, default: bool) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "on"}


DB_URL = os.getenv("KISAN_DB_URL", f"sqlite:///{RUNTIME_DIR / 'kisan.db'}")

# LLM: used only when a key is present and not switched off. Rule-based NLU is always the fallback.
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
USE_LLM = _bool("KISAN_USE_LLM", bool(ANTHROPIC_API_KEY))
LLM_EXTRACT_MODEL = os.getenv("KISAN_EXTRACT_MODEL", "claude-sonnet-5-5")
LLM_INTENT_MODEL = os.getenv("KISAN_INTENT_MODEL", "claude-haiku-5-5")

# Voice (Sarvam AI). Without a key, voice notes ask the farmer to type instead.
SARVAM_API_KEY = os.getenv("SARVAM_API_KEY", "")
SARVAM_STT_MODEL = os.getenv("SARVAM_STT_MODEL", "saarika:v2.5")
SARVAM_TTS_MODEL = os.getenv("SARVAM_TTS_MODEL", "bulbul:v2")
SARVAM_TTS_SPEAKER = os.getenv("SARVAM_TTS_SPEAKER", "anushka")

# WhatsApp via Twilio
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_WHATSAPP_FROM = os.getenv("TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886")
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://localhost:8000")

# Weather: live Open-Meteo first, recorded fixtures if the network call fails
WEATHER_LIVE = _bool("KISAN_WEATHER_LIVE", True)
WEATHER_TIMEOUT_S = float(os.getenv("KISAN_WEATHER_TIMEOUT_S", "8"))

# Planner thresholds
REPORT_WINDOW_H = 72
REPORT_NOW_THRESHOLD_H = float(os.getenv("KISAN_REPORT_NOW_H", "12"))
PHOTO_MAX_KM = float(os.getenv("KISAN_PHOTO_MAX_KM", "5"))
MIN_VALID_PHOTOS = 2
SURVEY_SLA_DAYS = 10          # PMFBY: loss assessment to be completed within 10 days of intimation
STATUS_STALL_DAYS = 30        # unchanged status for this long -> escalate
YIELD_RTI_GRACE_DAYS = 30     # yield data this late past expected date -> RTI draft
BIGHA_TO_HA = 0.2529          # Rajasthan pucca bigha (approx.); always read back to farmer for confirmation

CHANNEL_ORDER = os.getenv(
    "KISAN_CHANNEL_ORDER", "insurer_app,helpline_14447,insurer_office,bank_branch,csc"
).split(",")

# Cost tracking (approximate, for the eval's cost metric)
USD_TO_INR = float(os.getenv("KISAN_USD_TO_INR", "84"))
LLM_PRICE_PER_MTOK = {  # (input, output) USD
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-opus-5-5": (4.0, 20.0),
}
STT_INR_PER_MIN = float(os.getenv("KISAN_STT_INR_PER_MIN", "0.5"))
