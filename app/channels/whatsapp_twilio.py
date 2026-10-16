"""WhatsApp over Twilio (sandbox for the hackathon).

Inbound: Twilio POSTs form fields (From, Body, NumMedia, MediaUrl0, MediaContentType0, Latitude, Longitude).
Outbound: REST API, so scheduled follow-ups can message the farmer weeks later.
Note: Twilio does not tell us whether a WhatsApp image was forwarded, so `forwarded` stays None.
"""
from __future__ import annotations

import logging
import mimetypes
import uuid
from typing import Optional

import httpx

from app import config
from app.models.case import Message

log = logging.getLogger(__name__)
MEDIA_DIR = config.RUNTIME_DIR / "inbound"


def enabled() -> bool:
    return bool(config.TWILIO_ACCOUNT_SID and config.TWILIO_AUTH_TOKEN)


def download_media(url: str, content_type: str) -> Optional[str]:
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    ext = mimetypes.guess_extension(content_type.split(";")[0]) or ".bin"
    path = MEDIA_DIR / f"{uuid.uuid4().hex}{ext}"
    try:
        r = httpx.get(url, auth=(config.TWILIO_ACCOUNT_SID, config.TWILIO_AUTH_TOKEN), follow_redirects=True,
                      timeout=30)
        r.raise_for_status()
        path.write_bytes(r.content)
        return str(path)
    except Exception as e:
        log.warning("media download failed: %s", e)
        return None


def public_url(local_path: str) -> Optional[str]:
    try:
        rel = str(local_path).split(str(config.RUNTIME_DIR) + "/", 1)[1]
    except IndexError:
        return None
    return f"{config.PUBLIC_BASE_URL}/files/{rel}"


def send(to: str, m: Message) -> bool:
    if not enabled():
        return False
    url = f"https://api.twilio.com/2010-04-01/Accounts/{config.TWILIO_ACCOUNT_SID}/Messages.json"
    base = {"From": config.TWILIO_WHATSAPP_FROM, "To": to}
    payloads = [{**base, "Body": (m.text or "")[:1500]}]
    for p in (m.audio_path, m.media_path):
        if p and (u := public_url(p)):
            payloads.append({**base, "MediaUrl": u})
    try:
        for data in payloads:
            r = httpx.post(url, data=data, auth=(config.TWILIO_ACCOUNT_SID, config.TWILIO_AUTH_TOKEN), timeout=30)
            r.raise_for_status()
        return True
    except Exception as e:
        log.warning("twilio send failed: %s", e)
        return False
