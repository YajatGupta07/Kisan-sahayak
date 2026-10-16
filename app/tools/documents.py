"""PDF documents: channel-attempt log (proof), report receipt, grievance, RTI, enrolment correction.

Documents are in English (the farmer gets a Hindi summary in chat). Drafts are only *submitted*
through consent.py after the farmer confirms the Hindi read-back.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Iterable

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app import config

DOC_DIR = config.RUNTIME_DIR / "docs"
DOC_DIR.mkdir(parents=True, exist_ok=True)
_styles = getSampleStyleSheet()


def _fmt(dt) -> str:
    return dt.strftime("%d %b %Y, %H:%M IST") if isinstance(dt, datetime) else str(dt or "-")


def _build(path: Path, title: str, paras: Iterable, table: list[list] | None = None, mock: bool = False) -> str:
    doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm)
    story = []
    if mock:
        story.append(Paragraph('<font color="#b00020"><b>[MOCK] Demonstration document — insurer systems are '
                               'simulated. Not a real submission.</b></font>', _styles["Normal"]))
        story.append(Spacer(1, 4 * mm))
    story += [Paragraph(title, _styles["Title"]), Spacer(1, 3 * mm)]
    for p in paras:
        story += [Paragraph(p, _styles["Normal"]), Spacer(1, 2.5 * mm)]
    if table:
        t = Table(table, repeatRows=1)
        t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
                               ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8f0e3")),
                               ("FONTSIZE", (0, 0), (-1, -1), 8), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
        story.append(t)
    doc.build(story)
    return str(path)


def _case_lines(case) -> list[str]:
    return [
        f"<b>Case:</b> KS-{case.id:05d} &nbsp; <b>Farmer:</b> {case.farmer_name_masked or '-'} ({case.phone_masked})",
        f"<b>Policy:</b> {case.policy_no or '-'} &nbsp; <b>Season:</b> {case.season or '-'} &nbsp; "
        f"<b>Crop insured:</b> {case.crop_insured or '-'}",
        f"<b>Plot:</b> village {case.village or '-'}, khasra {case.khasra or '-'}, IU {case.iu_code or '-'}",
        f"<b>Loss:</b> {case.event_type or '-'} at {_fmt(case.event_at)}; reporting deadline {_fmt(case.deadline_at)}",
    ]


def attempt_log(case, attempts, now: datetime) -> str:
    rows = [["#", "Channel", "Started", "Result", "Reference", "Response"]]
    for i, a in enumerate(attempts, 1):
        rows.append([str(i), a.channel, _fmt(a.started_at), a.result, a.ref_no or "-",
                     Paragraph((a.raw or "")[:160], _styles["Normal"])])
    paras = _case_lines(case) + [
        f"Generated {_fmt(now)}. This log records every attempt made on the farmer's behalf to intimate the "
        "loss, with timestamps and the response received, so that a missed deadline can be contested.",
    ]
    return _build(DOC_DIR / f"case{case.id}_attempt_log_{now:%Y%m%d%H%M}.pdf", "Loss-intimation attempt log",
                  paras, rows, mock=True)


def report_receipt(case, now: datetime) -> str:
    paras = _case_lines(case) + [
        f"<b>Reported via:</b> {case.report_channel} &nbsp; <b>Reference no.:</b> {case.reference_no}",
        f"<b>Reported at:</b> {_fmt(case.reported_at)} "
        f"({'within' if case.reported_at and case.deadline_at and case.reported_at <= case.deadline_at else 'AFTER'} "
        "the 72-hour window)",
        f"<b>Area claimed:</b> {case.area_ha} ha (confirmed by farmer)",
        "Do not clear or harvest the damaged field before the loss assessor's survey.",
    ]
    return _build(DOC_DIR / f"case{case.id}_report_receipt.pdf", "Crop loss intimation — receipt", paras, mock=True)


def grievance(case, reason: str, detail: str, now: datetime) -> str:
    paras = ["To: Krishi Rakshak Portal / District Grievance Redressal Committee, Alwar", f"Date: {_fmt(now)}",
             "<b>Subject:</b> Grievance regarding PMFBY claim — " + reason] + _case_lines(case) + [
        f"<b>Reference no. of loss intimation:</b> {case.reference_no or 'n/a (area-based claim)'}",
        "<b>Grievance:</b> " + detail,
        "The farmer requests that the matter be resolved and the claim settled as per the PMFBY operational "
        "guidelines. Supporting evidence (photos, attempt log, status history) is attached in the case record.",
        "Submitted with the farmer's explicit consent after a Hindi read-back.",
    ]
    return _build(DOC_DIR / f"case{case.id}_grievance_{now:%Y%m%d%H%M}.pdf", "PMFBY grievance", paras, mock=True)


def rti(case, iu: str, crop: str, season: str, now: datetime) -> str:
    paras = [
        "To: The Public Information Officer, Directorate of Agriculture, Rajasthan, Jaipur",
        f"Date: {_fmt(now)}",
        "<b>Subject:</b> Application under Section 6(1) of the Right to Information Act, 2005",
        "Please provide the following information:",
        f"1. Crop Cutting Experiment (CCE) results and the actual yield computed for insurance unit {iu}, "
        f"crop {crop}, season {season}, Alwar district.",
        "2. The threshold yield notified for the same insurance unit, crop and season.",
        "3. The date on which the yield data was transmitted to the insurance company.",
        "Application fee of Rs 10 is paid by the applicant (BPL applicants are exempt).",
        f"Applicant: {case.farmer_name_masked or '-'} (details withheld in this draft). Prepared with consent.",
    ]
    return _build(DOC_DIR / f"case{case.id}_rti_{now:%Y%m%d%H%M}.pdf", "RTI application (draft)", paras)


def enrolment_correction(case, insured_crop: str, sown_crop: str, now: datetime) -> str:
    paras = ["To: Branch Manager / CSC operator that enrolled the farmer; copy: insurer district office",
             f"Date: {_fmt(now)}",
             "<b>Subject:</b> Request to correct crop recorded in PMFBY enrolment"] + _case_lines(case) + [
        f"The policy records the crop as <b>{insured_crop}</b>, while the crop actually sown on the plot is "
        f"<b>{sown_crop}</b> (farmer statement and field photographs on record).",
        "Request: correct the crop in the enrolment data, or confirm in writing what correction route applies "
        "for this season. A claim is not being filed against the incorrect crop.",
    ]
    return _build(DOC_DIR / f"case{case.id}_enrolment_correction.pdf", "Enrolment correction request", paras)
