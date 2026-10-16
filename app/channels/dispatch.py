"""Deliver outbound messages. Simulator messages are just marked delivered (the UI reads the DB);
WhatsApp messages go out through Twilio's REST API (needed for scheduled follow-ups)."""
from __future__ import annotations

import logging

from sqlalchemy import select

from app.db import session_scope
from app.models.case import Case, Message

log = logging.getLogger(__name__)


def flush() -> int:
    from app.channels import whatsapp_twilio
    sent = 0
    with session_scope() as db:
        rows = db.execute(select(Message, Case).join(Case, Case.id == Message.case_id)
                          .where(Message.direction == "out", Message.delivered.is_(False))
                          .order_by(Message.id)).all()
        for m, case in rows:
            if case.channel == "whatsapp":
                phone = (case.flags or {}).get("_wa_from")
                if not phone or not whatsapp_twilio.send(phone, m):
                    continue
            m.delivered = True
            sent += 1
    return sent
