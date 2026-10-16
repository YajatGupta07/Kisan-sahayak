"""Generate the 50 evaluation scenarios -> data/eval/scenarios.json

Mix (plan §8): 20 reporting (with channel faults), 15 payability (past seasons), 10 incorrect policy data,
5 photo/identifier failures. Ground truth for payability is computed here independently of the agent code.
All data is ILLUSTRATIVE (see data/alwar/*.json).
"""
from __future__ import annotations

import json
import random
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
rng = random.Random(7)
BIGHA = 0.2529
YIELDS = json.loads((ROOT / "data/alwar/yields.json").read_text())
UNITS = json.loads((ROOT / "data/alwar/insurance_units.json").read_text())["units"]
VILLAGES = [(v["name"], u["iu_code"], v["lat"], v["lon"]) for u in UNITS for v in u["villages"]]
SI_HA = {"mustard": 58000, "wheat": 72000, "gram": 52000, "barley": 50000}
CROP_HI = {"mustard": "सरसों", "wheat": "गेहूं", "gram": "चना", "barley": "जौ"}
LOCAL_EVENTS = [("ओले गिरे", "hail"), ("खेत में पानी भर गया", "inundation"), ("बिजली गिरने से आग लग गई", "natural_fire")]
WIDE_EVENTS = [("पाला पड़ा", "frost"), ("बेमौसम बारिश हुई", "unseasonal_rain"), ("कीट/माहू लग गया", "pest")]
# (phrase, days before start, hour of event, start hour)
WHEN = [("कल शाम 6 बजे", 1, 18, 19), ("कल रात", 1, 22, 9), ("परसों शाम", 2, 18, 11), ("आज सुबह", 0, 7, 12),
        ("kal dopahar", 1, 13, 20), ("parson raat", 2, 22, 8)]
FAULT_SETS = [
    {}, {"insurer_app": "error"}, {"insurer_app": "timeout", "helpline_14447": "no_answer"},
    {"insurer_app": "invalid_ref"}, {"insurer_app": "error", "helpline_14447": "error_once"},
    {"insurer_app": "error_once", "helpline_14447": "error_once", "insurer_office": "error_once",
     "bank_branch": "error_once", "csc": "error_once"},
]


def ty(hist, ind=0.7):
    b = sorted(hist, reverse=True)[:5]
    return sum(b) / 5 * ind


def yield_row(iu, crop, season):
    return next(r for r in YIELDS["rows"] if r["iu_code"] == iu and r["crop"] == crop and r["season"] == season)


def policy(no, crop, village, iu, area_ha, season, **kw):
    return {"policy_no": no, "receipt_no": no, "loan_account": kw.get("loan"), "farmer_name_masked": "E*** F***",
            "season": season, "crop": crop, "village": village, "iu_code": iu, "khasra": [str(rng.randint(10, 999))],
            "area_ha": area_ha, "sum_insured_per_ha": SI_HA[crop], "insurer": "Season insurer (illustrative)",
            "bank": {"name": f"Bank, {village}", "account_masked": f"XXXXXXXX{rng.randint(1000, 9999)}",
                     "aadhaar_seeded": kw.get("seeded", True), "npci_mapped": True},
            "mapped_to_iu": kw.get("mapped", True), "otp_required": kw.get("otp", False),
            "claim_timeline": kw.get("timeline", {}), "illustrative": True}


def reporting(i: int, *, photos="good", faults=None, near_deadline=False, harvested=False):
    village, iu, lat, lon = rng.choice(VILLAGES)
    crop = rng.choice(["mustard", "wheat"])
    ev_hi, ev = rng.choice(LOCAL_EVENTS) if not harvested else ("बेमौसम बारिश से कटी हुई फसल भीग गई", "unseasonal_rain")
    phrase, back, ev_h, st_h = WHEN[i % len(WHEN)]
    if near_deadline:
        phrase, back, ev_h, st_h = ("परसों सुबह", 2, 7, 21)
    day = datetime(2026, 3, 10) + timedelta(days=i % 5)
    start = day.replace(hour=st_h, minute=15)
    event_at = (day - timedelta(days=back)).replace(hour=ev_h)
    area_b = rng.choice([1, 2, 3])
    area_ha = round(max(area_b * BIGHA, rng.choice([0.5, 0.76, 1.01])), 2)
    no = f"RJ25E{i:06d}"
    loss = rng.choice([30, 40, 55])
    p = policy(no, crop, village, iu, area_ha, "rabi_2025_26",
               timeline={"survey_day": 4, "assessment_day": 7, "loss_pct": loss, "payment": {"mode": "paid", "day": 20}})
    return {
        "category": "reporting", "start": start.isoformat(), "event_at": event_at.isoformat(),
        "opening": f"{phrase} {ev_hi}, मेरी {CROP_HI[crop]} की फसल खराब हो गई, {area_b} बीघा में नुकसान",
        "truth": {"event_type": ev, "crop": crop, "area_bigha": area_b, "receipt": no, "village": village,
                  "lat": lat, "lon": lon},
        "faults": faults or {}, "policy": p, "photos": photos, "advance_days": 45,
        "expect": {"reported": True, "outcome": "CLOSED_PAID"},
        "injected": (1 if faults else 0),
    }


def payability(i: int):
    village, iu, lat, lon = rng.choice(VILLAGES)
    crop = rng.choice(["mustard", "wheat", "gram"])
    season = rng.choice(["rabi_2021_22", "rabi_2022_23", "rabi_2023_24", "rabi_2024_25"])
    if i % 3 == 0:  # make sure payable seasons are represented (designed shocks)
        iu, crop, season = rng.choice([("ALW-RMG-01", "mustard", "rabi_2022_23"), ("ALW-KTM-08", "mustard", "rabi_2022_23"),
                                      ("ALW-TJR-07", "wheat", "rabi_2023_24"), ("ALW-MKH-05", "gram", "rabi_2024_25")])
        village = next(v[0] for v in VILLAGES if v[1] == iu)
    if season == "rabi_2024_25" and crop == "wheat" and iu == "ALW-KBS-06":
        crop = "mustard"
    row = yield_row(iu, crop, season)
    t = ty(row["history_kg_ha"])
    area_ha = rng.choice([0.5, 0.76, 1.01, 1.26])
    si = round(area_ha * SI_HA[crop])
    payable = row["actual_kg_ha"] < t
    amount = round((t - row["actual_kg_ha"]) / t * si) if payable else 0
    y0 = int(season.split("_")[1])
    start = datetime(y0 + 1, 1, 10 + i % 15, 10, 0)
    no = f"RJ{y0 % 100:02d}W{i:06d}"
    ev_hi, ev = rng.choice(WIDE_EVENTS)
    p = policy(no, crop, village, iu, area_ha, season, timeline={"payment": {"mode": "paid", "day": 20}})
    return {
        "category": "payability", "start": start.isoformat(),
        "opening": f"कल {ev_hi}, पूरे गांव में सबकी {CROP_HI[crop]} खराब हो गई",
        "truth": {"event_type": ev, "crop": crop, "receipt": no, "village": village, "lat": lat, "lon": lon},
        "faults": {}, "policy": p, "photos": "none", "advance_days": 260,
        "expect": {"reported": False, "payable": payable, "amount": amount,
                   "outcome": "CLOSED_PAID" if payable else "CLOSED_NOT_PAYABLE",
                   "figures": {"actual": row["actual_kg_ha"], "threshold": round(t)}},
        "injected": 0,
    }


def policy_data(i: int, kind: str):
    if kind == "crop_mismatch":
        s = reporting(100 + i)
        sown = {"mustard": "gram", "wheat": "barley"}[s["policy"]["crop"]]
        s["opening"] = s["opening"].replace(CROP_HI[s["policy"]["crop"]], CROP_HI[sown])
        s["truth"]["crop"] = sown
        s["category"] = "policy_data"
        s["expect"] = {"reported": False, "outcome": "BLOCKED", "blocker_contains": "differs"}
        s["injected"] = 1
        return s
    if kind in ("unseeded", "unmapped"):
        s = payability(3 * i)  # i*3 -> designed payable season
        s["category"] = "policy_data"
        if kind == "unseeded":
            s["policy"]["bank"]["aadhaar_seeded"] = False
            s["policy"]["claim_timeline"] = {"payment": {"mode": "failed", "code": "ACCOUNT_NOT_SEEDED", "day": 20}}
            s["expect"].update({"outcome": "BLOCKED", "blocker_contains": "seeded"})
        else:
            s["policy"]["mapped_to_iu"] = False
            s["policy"]["claim_timeline"] = {"payment": {"mode": "pending", "code": "FARMER_NOT_IN_IU_LIST", "day": 20}}
            s["expect"].update({"outcome": "BLOCKED", "blocker_contains": "mapped"})
        s["injected"] = 1
        return s
    if kind == "loan_otp":
        s = reporting(120 + i)
        s["policy"]["loan_account"] = f"5{rng.randint(10**9, 10**10 - 1)}"
        s["policy"]["otp_required"] = True
        s["truth"]["loan"] = s["policy"]["loan_account"]
        s["truth"]["receipt"] = None
        s["category"] = "policy_data"
        s["injected"] = 1
        return s
    raise ValueError(kind)


def photo_failure(i: int, kind: str):
    s = reporting(140 + i, photos=kind)
    s["category"] = "photo_identifier"
    s["injected"] = 1
    if kind == "wrong_receipt_first":
        s["photos"] = "good"
        s["truth"]["wrong_receipt_first"] = True
    return s


def main():
    sc = []
    for i in range(20):
        faults = FAULT_SETS[i % len(FAULT_SETS)]
        photos = ["good", "none", "good", "good"][i % 4]
        sc.append(reporting(i, photos=photos, faults=faults, near_deadline=(i % 7 == 6), harvested=(i % 9 == 4)))
    for i in range(15):
        sc.append(payability(i))
    for i, kind in enumerate(["crop_mismatch"] * 5 + ["unseeded", "unseeded", "unmapped", "unmapped", "loan_otp"]):
        sc.append(policy_data(i, kind))
    for i, kind in enumerate(["dark_then_good", "forwarded_then_good", "noexif_then_location", "wrong_receipt_first",
                              "far_then_good"]):
        sc.append(photo_failure(i, kind))
    for n, s in enumerate(sc, 1):
        s["id"] = f"S{n:02d}"
        s["phone"] = f"+9197{n:08d}"
        # harvested scenarios are post-harvest (individual) claims
    out = ROOT / "data/eval/scenarios.json"
    out.write_text(json.dumps(sc, ensure_ascii=False, indent=1))
    from collections import Counter
    print("wrote", out.relative_to(ROOT), Counter(s["category"] for s in sc))


if __name__ == "__main__":
    main()
