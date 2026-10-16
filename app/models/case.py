"""Case record. All datetimes are naive IST (Asia/Kolkata) produced by app.clock."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _token() -> str:
    return uuid.uuid4().hex[:12]


class Case(Base):
    __tablename__ = "cases"

    id: Mapped[int] = mapped_column(primary_key=True)
    token: Mapped[str] = mapped_column(String(16), default=_token, unique=True)  # capture-page link
    phone_hash: Mapped[str] = mapped_column(String(64), index=True)
    phone_masked: Mapped[str] = mapped_column(String(20))
    channel: Mapped[str] = mapped_column(String(20), default="simulator")  # simulator | whatsapp
    farmer_name_masked: Mapped[Optional[str]] = mapped_column(String(64))
    language: Mapped[str] = mapped_column(String(8), default="hi")

    state: Mapped[str] = mapped_column(String(32), default="NEW")
    claim_type: Mapped[Optional[str]] = mapped_column(String(16))

    event_type: Mapped[Optional[str]] = mapped_column(String(32))
    event_time_text: Mapped[Optional[str]] = mapped_column(String(200))
    event_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    harvest_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    deadline_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    season: Mapped[Optional[str]] = mapped_column(String(20))

    crop_reported: Mapped[Optional[str]] = mapped_column(String(20))
    crop_insured: Mapped[Optional[str]] = mapped_column(String(20))
    policy_no: Mapped[Optional[str]] = mapped_column(String(40))
    village: Mapped[Optional[str]] = mapped_column(String(60))
    khasra: Mapped[Optional[str]] = mapped_column(String(20))
    iu_code: Mapped[Optional[str]] = mapped_column(String(20))
    area_ha: Mapped[Optional[float]] = mapped_column(Float)
    insured_area_ha: Mapped[Optional[float]] = mapped_column(Float)
    sum_insured: Mapped[Optional[float]] = mapped_column(Float)  # Rs, for the insured area

    reference_no: Mapped[Optional[str]] = mapped_column(String(40))
    report_channel: Mapped[Optional[str]] = mapped_column(String(32))
    reported_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    outcome: Mapped[Optional[str]] = mapped_column(String(32))
    blocker: Mapped[Optional[str]] = mapped_column(String(200))
    next_step: Mapped[Optional[str]] = mapped_column(String(300))
    paid_amount: Mapped[Optional[float]] = mapped_column(Float)
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    pending_action_id: Mapped[Optional[int]] = mapped_column(Integer)
    flags: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    cost_inr: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime)

    facts: Mapped[list["Fact"]] = relationship(back_populates="case", order_by="Fact.id")
    messages: Mapped[list["Message"]] = relationship(back_populates="case", order_by="Message.id")

    def flag(self, key: str, default=None):
        return (self.flags or {}).get(key, default)

    def set_flag(self, key: str, value) -> None:
        f = dict(self.flags or {})
        f[key] = value
        self.flags = f  # reassign so SQLAlchemy sees the change


class Fact(Base):
    """Provenance for every important value."""
    __tablename__ = "facts"

    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id"), index=True)
    key: Mapped[str] = mapped_column(String(40))
    value: Mapped[Any] = mapped_column(JSON)
    source: Mapped[str] = mapped_column(String(20))
    confirmed_by_farmer: Mapped[bool] = mapped_column(Boolean, default=False)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime)
    evidence_ref: Mapped[Optional[str]] = mapped_column(String(200))
    mock: Mapped[bool] = mapped_column(Boolean, default=False)
    illustrative: Mapped[bool] = mapped_column(Boolean, default=False)
    note: Mapped[Optional[str]] = mapped_column(String(300))

    case: Mapped[Case] = relationship(back_populates="facts")


class Evidence(Base):
    __tablename__ = "evidence"

    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20))  # photo | voice | document | location
    sha256: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    received_at: Mapped[datetime] = mapped_column(DateTime)
    captured_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    lat: Mapped[Optional[float]] = mapped_column(Float)
    lon: Mapped[Optional[float]] = mapped_column(Float)
    capture_method: Mapped[Optional[str]] = mapped_column(String(20))  # capture_page | document | photo
    exif_ok: Mapped[Optional[bool]] = mapped_column(Boolean)
    forwarded: Mapped[Optional[bool]] = mapped_column(Boolean)  # None = channel can't tell
    crop_detected: Mapped[Optional[str]] = mapped_column(String(20))
    damage_detected: Mapped[Optional[str]] = mapped_column(String(40))
    valid: Mapped[bool] = mapped_column(Boolean, default=False)
    problems: Mapped[list] = mapped_column(JSON, default=list)
    path: Mapped[Optional[str]] = mapped_column(String(300))
    title: Mapped[Optional[str]] = mapped_column(String(120))


class ChannelAttempt(Base):
    __tablename__ = "channel_attempts"

    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id"), index=True)
    channel: Mapped[str] = mapped_column(String(32))
    started_at: Mapped[datetime] = mapped_column(DateTime)
    result: Mapped[str] = mapped_column(String(20))  # ok | error | timeout | no_answer | invalid_ref | skipped_closed
    ref_no: Mapped[Optional[str]] = mapped_column(String(40))
    raw: Mapped[Optional[str]] = mapped_column(Text)
    mock: Mapped[bool] = mapped_column(Boolean, default=True)


class Action(Base):
    """Consequential (or confirm-needed) actions. Only consent.py moves these to EXECUTED."""
    __tablename__ = "actions"

    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id"), index=True)
    kind: Mapped[str] = mapped_column(String(32))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    readback_text_hi: Mapped[str] = mapped_column(Text)
    readback_audio: Mapped[Optional[str]] = mapped_column(String(300))
    readback_message_id: Mapped[Optional[int]] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="PENDING")
    created_at: Mapped[datetime] = mapped_column(DateTime)
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    confirmation_message_id: Mapped[Optional[int]] = mapped_column(Integer)
    result: Mapped[Optional[dict]] = mapped_column(JSON)


class Decision(Base):
    """Planner trace: what was chosen and why. Shown on the dashboard."""
    __tablename__ = "decisions"

    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id"), index=True)
    at: Mapped[datetime] = mapped_column(DateTime)
    state: Mapped[str] = mapped_column(String(32))
    chosen_action: Mapped[str] = mapped_column(String(60))
    reason: Mapped[str] = mapped_column(Text)
    inputs: Mapped[Optional[dict]] = mapped_column(JSON)


class ScheduledCheck(Base):
    __tablename__ = "scheduled_checks"

    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id"), index=True)
    kind: Mapped[str] = mapped_column(String(24))
    due_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    done: Mapped[bool] = mapped_column(Boolean, default=False)
    note: Mapped[Optional[str]] = mapped_column(String(200))


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id"), index=True)
    direction: Mapped[str] = mapped_column(String(4))  # in | out
    at: Mapped[datetime] = mapped_column(DateTime)
    text: Mapped[Optional[str]] = mapped_column(Text)
    media_kind: Mapped[Optional[str]] = mapped_column(String(20))
    media_path: Mapped[Optional[str]] = mapped_column(String(300))
    audio_path: Mapped[Optional[str]] = mapped_column(String(300))
    meta: Mapped[dict] = mapped_column(JSON, default=dict)  # e.g. {"ask": "policy_id", "mock": true}
    delivered: Mapped[bool] = mapped_column(Boolean, default=False)

    case: Mapped[Case] = relationship(back_populates="messages")


class KV(Base):
    """Small global settings: clock offset, fault injection, demo toggles."""
    __tablename__ = "kv"

    key: Mapped[str] = mapped_column(String(40), primary_key=True)
    value: Mapped[Any] = mapped_column(JSON)
