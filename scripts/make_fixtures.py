"""Generate the ILLUSTRATIVE demo/eval data files.

Every row produced here is labelled illustrative. Replace `data/alwar/yields.json` with published
CCE / threshold-yield figures (with a source_url per row) once the Day-1 data check finds them.

Run:  python scripts/make_fixtures.py
"""
from __future__ import annotations

import json
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
rng = random.Random(42)

IUS = ["ALW-RMG-01", "ALW-LXG-02", "ALW-RJG-03", "ALW-THG-04", "ALW-MKH-05", "ALW-KBS-06", "ALW-TJR-07", "ALW-KTM-08"]
CROPS = {"mustard": 1550, "wheat": 4250, "gram": 1150, "barley": 3300}
HARVEST_YEARS = list(range(2015, 2027))  # harvest year of each Rabi season (rabi_2025_26 -> 2026)
SEASONS = {2022: "rabi_2021_22", 2023: "rabi_2022_23", 2024: "rabi_2023_24", 2025: "rabi_2024_25", 2026: "rabi_2025_26"}

# Designed shocks (fraction of normal yield) so every follow-up route has data behind it
SHOCKS = {
    ("ALW-KTM-08", "mustard", 2026): 0.52,   # frost: payable (demo 2)
    ("ALW-RJG-03", "mustard", 2026): 0.93,   # widespread complaints but IU above threshold (demo 3)
    ("ALW-LXG-02", "wheat", 2026): 0.55,     # payable (mapping-error case)
    ("ALW-KBS-06", "wheat", 2025): 0.50,     # payable in 2024-25 (subsidy-delay case)
    ("ALW-RMG-01", "mustard", 2023): 0.60,
    ("ALW-KTM-08", "mustard", 2023): 0.58,
    ("ALW-TJR-07", "wheat", 2024): 0.62,
    ("ALW-MKH-05", "gram", 2025): 0.55,
}
UNPUBLISHED = {("ALW-THG-04", "wheat", 2026)}  # yield data not out -> RTI route


def series(iu: str, crop: str) -> dict[int, int]:
    base = CROPS[crop] * rng.uniform(0.88, 1.12)
    out = {}
    for y in HARVEST_YEARS:
        trend = 1 + 0.01 * (y - 2015)
        v = base * trend * rng.uniform(0.9, 1.1) * SHOCKS.get((iu, crop, y), 1.0)
        out[y] = int(round(v))
    return out


def yields():
    rows = []
    for iu in IUS:
        for crop in CROPS:
            s = series(iu, crop)
            for hy, season in SEASONS.items():
                hist = [s[y] for y in range(hy - 7, hy)]
                rows.append({
                    "iu_code": iu, "crop": crop, "season": season,
                    "history_kg_ha": hist,  # previous 7 seasons, oldest first
                    "actual_kg_ha": None if (iu, crop, hy) in UNPUBLISHED else s[hy],
                    "source_url": None, "illustrative": True,
                })
    return {
        "_about": "ILLUSTRATIVE yields for demo/eval. TY = mean(best 5 of last 7) x indemnity level. "
                  "Replace with published CCE/threshold data and set source_url per row.",
        "indemnity_level": {"mustard": 0.7, "wheat": 0.7, "gram": 0.7, "barley": 0.7},
        "seasons": {
            "rabi_2021_22": {"expected_publish": "2022-07-31", "published_on": "2022-07-20"},
            "rabi_2022_23": {"expected_publish": "2023-07-31", "published_on": "2023-07-25"},
            "rabi_2023_24": {"expected_publish": "2024-07-31", "published_on": "2024-07-18"},
            "rabi_2024_25": {"expected_publish": "2025-07-31", "published_on": "2025-07-22"},
            "rabi_2025_26": {"expected_publish": "2026-07-31", "published_on": "2026-07-24"},
        },
        "rows": rows,
    }


def bank(name, seeded=True, mapped=True):
    return {"name": name, "account_masked": f"XXXXXXXX{rng.randint(1000, 9999)}", "aadhaar_seeded": seeded,
            "npci_mapped": mapped}


def policy(no, *, crop, village, iu, khasra, area, si_ha, season="rabi_2025_26", loan=None, otp=False,
           mapped=True, bank_info=None, timeline=None, name="R*** L**"):
    return {
        "policy_no": no, "receipt_no": no, "loan_account": loan, "farmer_name_masked": name,
        "season": season, "crop": crop, "village": village, "iu_code": iu, "khasra": [khasra],
        "area_ha": area, "sum_insured_per_ha": si_ha, "insurer": "Season insurer (illustrative)",
        "bank": bank_info or bank("State Bank of India, " + village), "mapped_to_iu": mapped,
        "otp_required": otp, "claim_timeline": timeline or {}, "illustrative": True,
    }


def policies():
    paid_localised = {"survey_day": 4, "assessment_day": 7, "loss_pct": 45, "payment": {"mode": "paid", "day": 24}}
    return {"_about": "ILLUSTRATIVE policy fixtures. No real farmer data. Day numbers are days after the loss "
                      "report (localised) or after yield publication (widespread).",
            "policies": [
        policy("RJ25R000101", crop="mustard", village="Ramgarh", iu="ALW-RMG-01", khasra="214", area=0.76,
               si_ha=58000, loan="31234567890", timeline=paid_localised),
        policy("RJ25R000102", crop="mustard", village="Laxmangarh", iu="ALW-LXG-02", khasra="88", area=0.5,
               si_ha=58000, name="S*** D***"),  # farmer actually sowed gram -> crop mismatch
        policy("RJ25R000103", crop="mustard", village="Kathumar", iu="ALW-KTM-08", khasra="1043", area=1.01,
               si_ha=58000, bank_info=bank("Bank of Baroda, Kathumar", seeded=False),
               timeline={"payment": {"mode": "failed", "code": "ACCOUNT_NOT_SEEDED", "day": 20}}, name="M*** S***"),
        policy("RJ25R000104", crop="mustard", village="Rajgarh", iu="ALW-RJG-03", khasra="512", area=0.76,
               si_ha=58000, name="G*** R**"),
        policy("RJ25R000105", crop="wheat", village="Naugaon", iu="ALW-RMG-01", khasra="77", area=0.5,
               si_ha=72000, timeline={"survey_day": None, "survey_after_grievance_day": 3, "assessment_day": 3,
                                       "loss_pct": 35, "payment": {"mode": "paid", "day": 21}}, name="H*** S***"),
        policy("RJ25R000106", crop="mustard", village="Malakhera", iu="ALW-MKH-05", khasra="301", area=0.5,
               si_ha=58000, loan="41234567890", otp=True, timeline=paid_localised, name="K*** D***"),
        policy("RJ25R000107", crop="wheat", village="Thanagazi", iu="ALW-THG-04", khasra="66", area=1.0,
               si_ha=72000, name="B*** L**"),
        policy("RJ25R000108", crop="wheat", village="Laxmangarh", iu="ALW-LXG-02", khasra="140", area=0.76,
               si_ha=72000, mapped=False,
               timeline={"payment": {"mode": "pending", "code": "FARMER_NOT_IN_IU_LIST", "day": 20}},
               name="J*** M***"),
        policy("RJ24R000109", crop="wheat", village="Kishangarh Bas", iu="ALW-KBS-06", khasra="905", area=0.5,
               si_ha=70000, season="rabi_2024_25",
               timeline={"payment": {"mode": "pending", "code": "AWAITING_FUNDS", "day": 25}}, name="P*** K***"),
        policy("RJ25R000110", crop="mustard", village="Umren", iu="ALW-MKH-05", khasra="45", area=0.5,
               si_ha=58000, timeline={"survey_day": 3, "assessment_day": 6, "loss_pct": 60,
                                       "payment": {"mode": "paid", "day": 25}}, name="A*** B***"),
        policy("RJ25R000111", crop="wheat", village="Tijara", iu="ALW-TJR-07", khasra="12", area=1.26,
               si_ha=72000, timeline={"survey_day": 5, "assessment_day": 8, "loss_pct": 30,
                                       "payment": {"mode": "paid", "day": 27}}, name="N*** K***"),
    ]}


def apna_khata(pols):
    out = {"_about": "ILLUSTRATIVE land-record fixtures (source label: fixture).", "plots": {}}
    for p in pols["policies"]:
        for k in p["khasra"]:
            out["plots"][f"{p['village']}|{k}"] = {"owner_masked": p["farmer_name_masked"], "area_ha": p["area_ha"],
                                                   "khata_no": str(rng.randint(10, 400))}
    return out


def weather():
    # Recorded/illustrative daily weather for the demo dates (used when Open-Meteo is unreachable).
    return {"_about": "ILLUSTRATIVE daily weather used only when the live Open-Meteo call fails.",
            "days": {
                "Ramgarh|2026-03-12": {"precip_mm": 21.4, "weather_code": 96, "wind_gust_kmh": 58, "tmin_c": 14.1,
                                       "tmax_c": 27.0},
                "Ramgarh|2026-03-11": {"precip_mm": 0.0, "weather_code": 2, "wind_gust_kmh": 22, "tmin_c": 15.2,
                                       "tmax_c": 31.0},
                "Naugaon|2026-03-12": {"precip_mm": 19.0, "weather_code": 96, "wind_gust_kmh": 55, "tmin_c": 14.0,
                                       "tmax_c": 27.5},
                "Kathumar|2026-01-14": {"precip_mm": 0.0, "weather_code": 0, "wind_gust_kmh": 9, "tmin_c": 0.4,
                                        "tmax_c": 19.0},
                "Rajgarh|2026-02-20": {"precip_mm": 6.2, "weather_code": 63, "wind_gust_kmh": 30, "tmin_c": 9.0,
                                       "tmax_c": 24.0},
                "Laxmangarh|2026-03-12": {"precip_mm": 0.0, "weather_code": 1, "wind_gust_kmh": 14, "tmin_c": 16.0,
                                          "tmax_c": 32.0},
            }}


def main():
    pols = policies()
    files = {
        ROOT / "data/alwar/yields.json": yields(),
        ROOT / "data/fixtures/policies.json": pols,
        ROOT / "data/fixtures/apna_khata.json": apna_khata(pols),
        ROOT / "data/alwar/weather_fixtures.json": weather(),
    }
    for path, obj in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(obj, ensure_ascii=False, indent=1))
        print("wrote", path.relative_to(ROOT))


if __name__ == "__main__":
    main()
