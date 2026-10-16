"""Demo helpers: synthetic field photos and the three scripted demos (used by the dashboard and eval)."""
from __future__ import annotations

import random
from datetime import datetime, timedelta
from fractions import Fraction
from typing import Optional

from PIL import Image, ImageDraw

from app import clock, config, kv
from app.channels import dispatch
from app.db import session_scope
from app.engine import conversation, scheduler
from app.models.case import Case

PHOTO_DIR = config.RUNTIME_DIR / "photos"
PHOTO_DIR.mkdir(parents=True, exist_ok=True)


def _dms(x: float):
    x = abs(x)
    d = int(x)
    m = int((x - d) * 60)
    s = round(((x - d) * 60 - m) * 60, 2)
    return (Fraction(d), Fraction(m), Fraction(s).limit_denominator(100))


def make_photo(name: str, *, taken_at: Optional[datetime] = None, lat: Optional[float] = None,
               lon: Optional[float] = None, crop: str = "mustard", dark: bool = False, seed: int = 0) -> str:
    """A synthetic 'field' JPEG, optionally with EXIF time and GPS (like a phone camera)."""
    rng = random.Random(f"{name}-{seed}")
    base = {"mustard": (200, 190, 60), "wheat": (190, 160, 90), "gram": (90, 140, 70), "barley": (180, 170, 110)}[crop]
    if dark:
        base = (8, 8, 8)
    img = Image.new("RGB", (640, 480), base)
    d = ImageDraw.Draw(img)
    if not dark:
        d.rectangle([0, 0, 640, 150], fill=(150, 190, 225))  # sky
        for row in range(160, 480, 18):  # crop rows
            d.line([(0, row), (640, row + 8)], fill=tuple(max(0, v - 50) for v in base), width=4)
        for _ in range(7):  # flattened / damaged patches
            x, y = rng.randint(0, 560), rng.randint(170, 420)
            d.ellipse([x, y, x + rng.randint(40, 110), y + rng.randint(20, 60)], fill=(120, 95, 60))
    for _ in range(0 if dark else 900):
        x, y = rng.randint(0, 639), rng.randint(150, 479)
        c = tuple(max(0, min(255, v + rng.randint(-70, 40))) for v in base)
        d.line([(x, y), (x + rng.randint(-6, 6), y + rng.randint(-20, -4))], fill=c, width=2)
    exif = Image.Exif()
    if taken_at:
        exif.get_ifd(0x8769)[36867] = taken_at.strftime("%Y:%m:%d %H:%M:%S")  # DateTimeOriginal
        exif[306] = taken_at.strftime("%Y:%m:%d %H:%M:%S")
    if lat is not None and lon is not None:
        gps = exif.get_ifd(0x8825)
        gps[1], gps[2] = ("N" if lat >= 0 else "S"), _dms(lat)
        gps[3], gps[4] = ("E" if lon >= 0 else "W"), _dms(lon)
    path = PHOTO_DIR / f"{name}.jpg"
    img.save(path, "JPEG", quality=85, exif=exif)
    return str(path)


def send(phone: str, **kw) -> int:
    with session_scope() as db:
        case = conversation.handle_inbound(db, phone, **kw)
        cid = case.id
    dispatch.flush()
    return cid


def reset_world() -> None:
    kv.set("faults", {})
    kv.set("force_crop_mismatch", False)
    kv.set("extra_policies", {})
    kv.set("extra_plots", {})


# ---------------------------------------------------------------- scripted demos
DEMO1_PHONE = "+919800000001"
DEMO2_PHONE = "+919800000002"
DEMO3_PHONE = "+919800000003"


def demo1_hail_app_outage(step_cb=None) -> int:
    """Hail on mustard (localised) + app outage -> helpline ref -> survey -> assessment -> paid."""
    reset_world()
    kv.set_fault("insurer_app", "error")
    clock.set_to(datetime(2026, 3, 13, 19, 30))
    p = DEMO1_PHONE
    steps = [
        dict(text="कल शाम 6 बजे ओले गिरे, मेरी सरसों की फसल खराब हो गई। 3 बीघा में नुकसान है।"),
        dict(text="हाँ"),
        dict(text="मेरी रसीद RJ25R000101 है"),
        dict(photo_path=make_photo("d1_a", taken_at=datetime(2026, 3, 13, 19, 35), lat=27.580, lon=76.805),
             as_document=True),
        dict(photo_path=make_photo("d1_b", taken_at=datetime(2026, 3, 13, 19, 36), lat=27.581, lon=76.806, seed=1),
             as_document=True),
        dict(text="हाँ"),
    ]
    cid = 0
    for s in steps:
        cid = send(p, **s)
        if step_cb:
            step_cb(cid)
        clock.advance(timedelta(minutes=2))
    return cid


def demo2_payable_unseeded(step_cb=None) -> int:
    """Frost (widespread) in Kathumar -> yield shows payable -> unpaid -> diagnosis: account not seeded -> grievance."""
    reset_world()
    clock.set_to(datetime(2026, 1, 15, 9, 0))
    p = DEMO2_PHONE
    cid = 0
    for s in [dict(text="कल रात पाला पड़ा, पूरे गांव की सरसों जल गई"), dict(text="पॉलिसी RJ25R000103")]:
        cid = send(p, **s)
        if step_cb:
            step_cb(cid)
    scheduler.advance_clock(datetime(2026, 9, 20, 10, 0) - clock.now())
    cid = send(p, text="हाँ")  # consent for the grievance
    return cid


def demo3_not_payable(step_cb=None) -> int:
    """Widespread rain damage complaint in Rajgarh -> IU yield above threshold -> no payout due, with figures."""
    reset_world()
    clock.set_to(datetime(2026, 2, 21, 11, 0))
    p = DEMO3_PHONE
    cid = 0
    for s in [dict(text="कल बेमौसम बारिश से हमारी सरसों खराब हो गई, पूरे गांव में सबकी फसल गई"),
              dict(text="रसीद नंबर RJ25R000104")]:
        cid = send(p, **s)
        if step_cb:
            step_cb(cid)
    scheduler.advance_clock(datetime(2026, 8, 1, 10, 0) - clock.now())
    return cid


def case_summary(cid: int) -> dict:
    with session_scope() as db:
        c = db.get(Case, cid)
        return {"id": c.id, "state": c.state, "outcome": c.outcome, "ref": c.reference_no, "blocker": c.blocker,
                "paid": c.paid_amount}
