"""FastAPI app: simulator API, Twilio WhatsApp webhook, photo capture page, case/clock endpoints.

Run:  uvicorn app.main:app --reload --port 8000
"""
from __future__ import annotations

import logging
import uuid
from datetime import timedelta
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, Response
from pydantic import BaseModel
from sqlalchemy import select

from app import clock, config, kv
from app.channels import dispatch, whatsapp_twilio
from app.db import init_db, session_scope
from app.engine import conversation, scheduler
from app.models.case import Case, Message

logging.basicConfig(level=logging.INFO)
app = FastAPI(title="Kisan Sahayak (Saakshi)")
init_db()


def _new_messages(case_id: int, after_id: int) -> list[dict]:
    with session_scope() as db:
        rows = db.scalars(select(Message).where(Message.case_id == case_id, Message.id > after_id,
                                                Message.direction == "out").order_by(Message.id))
        return [{"id": m.id, "text": m.text, "ask": (m.meta or {}).get("ask"), "audio": m.audio_path,
                 "media": m.media_path, "at": m.at.isoformat()} for m in rows]


def _last_id() -> int:
    with session_scope() as db:
        return db.scalar(select(Message.id).order_by(Message.id.desc()).limit(1)) or 0


# ---------------------------------------------------------------- simulator
class SimIn(BaseModel):
    phone: str
    text: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None


@app.post("/sim/message")
def sim_message(m: SimIn):
    before = _last_id()
    with session_scope() as db:
        case = conversation.handle_inbound(db, m.phone, text=m.text, lat=m.lat, lon=m.lon)
        cid, state = case.id, case.state
    dispatch.flush()
    return {"case_id": cid, "state": state, "replies": _new_messages(cid, before)}


@app.post("/sim/photo")
async def sim_photo(phone: str = Form(...), photo: UploadFile = File(...), as_document: bool = Form(False),
                    forwarded: Optional[bool] = Form(None), lat: Optional[float] = Form(None),
                    lon: Optional[float] = Form(None)):
    path = config.RUNTIME_DIR / "inbound" / f"{uuid.uuid4().hex}.jpg"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(await photo.read())
    before = _last_id()
    with session_scope() as db:
        case = conversation.handle_inbound(db, phone, photo_path=str(path), as_document=as_document,
                                           forwarded=forwarded, lat=lat, lon=lon)
        cid, state = case.id, case.state
    dispatch.flush()
    return {"case_id": cid, "state": state, "replies": _new_messages(cid, before)}


# ---------------------------------------------------------------- WhatsApp (Twilio)
@app.post("/webhook/whatsapp")
async def whatsapp_webhook(request: Request):
    form = dict(await request.form())
    phone = form.get("From", "")
    text = (form.get("Body") or "").strip() or None
    n_media = int(form.get("NumMedia", "0") or 0)
    photo_path = audio_path = None
    for i in range(n_media):
        ctype = form.get(f"MediaContentType{i}", "")
        path = whatsapp_twilio.download_media(form.get(f"MediaUrl{i}", ""), ctype)
        if not path:
            continue
        if ctype.startswith("image/"):
            photo_path = path
        elif ctype.startswith("audio/"):
            audio_path = path
        elif ctype == "application/pdf" or ctype.startswith("application/"):
            continue
    lat = float(form["Latitude"]) if form.get("Latitude") else None
    lon = float(form["Longitude"]) if form.get("Longitude") else None
    with session_scope() as db:
        case = conversation.get_or_create_case(db, phone, channel="whatsapp")
        case.set_flag("_wa_from", phone)  # needed to send scheduled follow-ups
        # An image sent "as document" arrives with its original file (EXIF kept); Twilio does not say which.
        conversation.handle_inbound(db, phone, text=text, photo_path=photo_path, as_document=True,
                                    audio_path=audio_path, lat=lat, lon=lon, channel="whatsapp", case=case)
    dispatch.flush()
    return Response(content="<?xml version='1.0' encoding='UTF-8'?><Response></Response>", media_type="application/xml")


# ---------------------------------------------------------------- capture page
@app.get("/capture/{token}", response_class=HTMLResponse)
def capture_page(token: str):
    with session_scope() as db:
        if not db.scalars(select(Case).where(Case.token == token)).first():
            raise HTTPException(404, "link expired")
    return (config.ROOT / "capture/index.html").read_text()


@app.post("/capture/{token}")
async def capture_upload(token: str, photo: UploadFile = File(...), lat: Optional[float] = Form(None),
                         lon: Optional[float] = Form(None), accuracy: Optional[float] = Form(None)):
    path = config.RUNTIME_DIR / "inbound" / f"cap_{uuid.uuid4().hex}.jpg"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(await photo.read())
    with session_scope() as db:
        case = db.scalars(select(Case).where(Case.token == token)).first()
        if not case:
            raise HTTPException(404, "link expired")
        before = _last_id()
        conversation.handle_inbound(db, "", photo_path=str(path), via_capture_page=True, lat=lat, lon=lon, case=case)
        ev = db.scalars(select(Message).where(Message.case_id == case.id, Message.id > before,
                                              Message.direction == "out").order_by(Message.id)).first()
        msg = ev.text if ev else "फोटो मिल गई"
    dispatch.flush()
    return {"valid": "✅" in msg, "message": msg}


# ---------------------------------------------------------------- case + demo control
@app.get("/cases")
def list_cases():
    with session_scope() as db:
        return [{"id": c.id, "phone": c.phone_masked, "state": c.state, "claim_type": c.claim_type,
                 "reference_no": c.reference_no, "outcome": c.outcome} for c in db.scalars(select(Case).order_by(Case.id))]


@app.get("/cases/{case_id}")
def get_case(case_id: int):
    with session_scope() as db:
        c = db.get(Case, case_id)
        if not c:
            raise HTTPException(404)
        return {"id": c.id, "state": c.state, "claim_type": c.claim_type, "deadline_at": c.deadline_at,
                "reference_no": c.reference_no, "outcome": c.outcome, "blocker": c.blocker, "next_step": c.next_step,
                "facts": [{"key": f.key, "value": f.value, "source": f.source, "confirmed": f.confirmed_by_farmer,
                           "mock": f.mock, "illustrative": f.illustrative} for f in c.facts]}


@app.post("/clock/advance")
def clock_advance(hours: float = 0, days: float = 0):
    n = scheduler.advance_clock(timedelta(hours=hours, days=days))
    return {"now": clock.now().isoformat(), "checks_run": n}


@app.post("/tick")
def tick():
    n = scheduler.tick()
    return {"now": clock.now().isoformat(), "checks_run": n}


@app.post("/faults/{channel}/{behaviour}")
def set_fault(channel: str, behaviour: str):
    kv.set_fault(channel, behaviour)
    return kv.faults()


@app.get("/files/{sub}/{name}")
def files(sub: str, name: str):
    if sub not in ("docs", "audio") or "/" in name or ".." in name:
        raise HTTPException(404)
    p = config.RUNTIME_DIR / sub / name
    if not p.exists():
        raise HTTPException(404)
    return FileResponse(p)


@app.get("/")
def root():
    return {"app": "Kisan Sahayak (Saakshi)", "now": clock.now().isoformat(), "llm": config.USE_LLM,
            "sarvam": bool(config.SARVAM_API_KEY), "twilio": whatsapp_twilio.enabled()}
