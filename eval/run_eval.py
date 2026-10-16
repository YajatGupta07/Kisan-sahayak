"""Run the 50 scenarios against the agent (and the information-only baseline) and write a report.

    python eval/generate.py      # once
    python eval/run_eval.py      # -> eval/results/report.md + results.json

The farmer side is a scripted simulator that answers from each scenario's ground truth, driven by the
`ask` tag on the agent's last message. Each farmer reply takes 3 simulated minutes.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("KISAN_WEATHER_LIVE", "0")

from sqlalchemy import select  # noqa: E402

from app import clock, demo, kv  # noqa: E402
from app.db import init_db, session_scope  # noqa: E402
from app.engine import consent, scheduler  # noqa: E402
from app.models.case import Case, ChannelAttempt, Evidence, Message  # noqa: E402
from eval import baseline_chatbot, report  # noqa: E402

FARMER_LATENCY = timedelta(minutes=3)
MAX_TURNS = 30


class Farmer:
    def __init__(self, s: dict):
        self.s, self.t = s, s["truth"]
        self.photo_queue = self._photos()
        self.gave_wrong = False
        self.said_no_photos = False

    def _photos(self) -> list[dict]:
        k = self.s["photos"]
        good = [{"kind": "good"}, {"kind": "good"}]
        return {"good": good, "none": [], "dark_then_good": [{"kind": "dark"}] + good,
                "forwarded_then_good": [{"kind": "forwarded"}] + good, "far_then_good": [{"kind": "far"}] + good,
                "noexif_then_location": [{"kind": "noexif"}, {"kind": "location"}, {"kind": "noexif"},
                                         {"kind": "location"}]}.get(k, good)

    def reply(self, ask: str | None, case_id: int) -> dict | None:
        t = self.t
        if ask == "confirm":
            return {"text": "हाँ"}
        if ask in ("event_type", "event_time", "crop", "correction"):
            return {"text": self.s["opening"]}
        if ask == "area":
            return {"text": f"{t.get('area_bigha', 1)} बीघा"}
        if ask == "policy_id":
            if t.get("wrong_receipt_first") and not self.gave_wrong:
                self.gave_wrong = True
                return {"text": "रसीद RJ25R999999"}
            if t.get("receipt"):
                return {"text": f"रसीद नंबर {t['receipt']}"}
            if t.get("loan"):
                return {"text": f"KCC लोन खाता {t['loan']}"}
            return None
        if ask == "otp":
            return {"text": "123456"}
        if ask == "photos":
            if self.photo_queue:
                p = self.photo_queue.pop(0)
                now = clock.now()
                lat, lon = t["lat"] + 0.002, t["lon"] + 0.002
                name = f"eval_{self.s['id']}_{len(self.photo_queue)}"
                if p["kind"] == "location":
                    return {"lat": lat, "lon": lon}
                if p["kind"] == "noexif":
                    path = demo.make_photo(name, crop=t["crop"])
                    return {"photo_path": path}
                if p["kind"] == "far":
                    lat += 0.3
                path = demo.make_photo(name, taken_at=now, lat=lat, lon=lon, crop=t["crop"], dark=p["kind"] == "dark")
                return {"photo_path": path, "as_document": True, "forwarded": p["kind"] == "forwarded"}
            if not self.said_no_photos:
                self.said_no_photos = True
                return {"text": "photo nahi hai"}
            return None
        return None


def last_ask(case_id: int) -> str | None:
    with session_scope() as db:
        m = db.scalars(select(Message).where(Message.case_id == case_id, Message.direction == "out")
                       .order_by(Message.id.desc())).first()
        c = db.get(Case, case_id)
        if consent.pending(db, c):
            return "confirm"
        return c.flag("awaiting") or ((m.meta or {}).get("ask") if m else None)


def run_scenario(s: dict) -> dict:
    tmp = tempfile.mkdtemp()
    init_db(f"sqlite:///{tmp}/eval.db", reset=True)
    demo.reset_world()
    kv.set("extra_policies", {s["policy"]["policy_no"]: s["policy"]})
    for ch, b in s["faults"].items():
        kv.set_fault(ch, b)
    clock.freeze(datetime.fromisoformat(s["start"]))
    farmer = Farmer(s)
    t0 = clock.now()
    cid = demo.send(s["phone"], text=s["opening"])
    turns = 1
    for _ in range(MAX_TURNS):
        ask = last_ask(cid)
        r = farmer.reply(ask, cid)
        if r is None:
            break
        clock.advance(FARMER_LATENCY)
        demo.send(s["phone"], **r)
        turns += 1
    # follow-up: jump in weekly steps, giving consent when the agent asks
    end = clock.now() + timedelta(days=s["advance_days"])
    while clock.now() < end:
        scheduler.advance_clock(min(timedelta(days=7), end - clock.now()))
        if last_ask(cid) == "confirm":
            clock.advance(FARMER_LATENCY)
            demo.send(s["phone"], text="हाँ")
    with session_scope() as db:
        c = db.get(Case, cid)
        attempts = list(db.scalars(select(ChannelAttempt).where(ChannelAttempt.case_id == cid)))
        photos = list(db.scalars(select(Evidence).where(Evidence.case_id == cid, Evidence.kind == "photo")))
        from app.engine import record
        est = record.latest_fact(db, c, "estimate_inr")
        res = {
            "id": s["id"], "category": s["category"], "state": c.state, "outcome": c.outcome,
            "claim_type": c.claim_type, "reference_no": c.reference_no,
            "reported_at": c.reported_at.isoformat() if c.reported_at else None,
            "deadline_at": c.deadline_at.isoformat() if c.deadline_at else None,
            "minutes_to_ref": round((c.reported_at - t0).total_seconds() / 60, 1) if c.reported_at else None,
            "attempts": [(a.channel, a.result) for a in attempts], "valid_photos": sum(p.valid for p in photos),
            "photo_problems": [p.problems for p in photos if not p.valid],
            "estimate_inr": est.value if est else None, "paid": c.paid_amount, "blocker": c.blocker,
            "cost_inr": round(c.cost_inr, 3), "turns": turns,
        }
    clock.freeze(None)
    return res


def score(s: dict, r: dict) -> dict:
    e = s["expect"]
    checks, reasons = {}, []
    if e.get("reported"):
        ok = bool(r["reference_no"]) and r["reported_at"] and r["reported_at"] <= r["deadline_at"]
        checks["reporting"] = ok
        if not ok:
            reasons.append(f"no valid ref within 72h (state {r['state']}, attempts {r['attempts']})")
    if "payable" in e:
        predicted_payable = r["estimate_inr"] is not None and r["state"] != "CLOSED_NOT_PAYABLE"
        ok = predicted_payable == e["payable"]
        if ok and e["payable"]:
            amt_ok = r["estimate_inr"] and abs(r["estimate_inr"] - e["amount"]) <= 0.15 * e["amount"]
            checks["amount"] = bool(amt_ok)
            if not amt_ok:
                reasons.append(f"amount {r['estimate_inr']} vs truth {e['amount']}")
        checks["payability"] = ok
        if not ok:
            reasons.append(f"payable={predicted_payable}, truth={e['payable']}")
    if e.get("outcome"):
        ok = r["state"] == e["outcome"] or r["outcome"] == e["outcome"]
        if e.get("blocker_contains"):
            ok = ok and e["blocker_contains"] in (r["blocker"] or "")
        checks["outcome"] = ok
        if not ok:
            reasons.append(f"outcome {r['state']}/{r['outcome']} (blocker: {r['blocker']}), expected {e['outcome']}")
    if s.get("injected"):
        checks["recovered"] = all(checks.values())
    return {"checks": checks, "pass": all(checks.values()), "reasons": reasons}


def main():
    scenarios = json.loads((ROOT / "data/eval/scenarios.json").read_text())
    only = set(sys.argv[1:])
    rows = []
    t_start = time.time()
    for s in scenarios:
        if only and s["id"] not in only:
            continue
        r = run_scenario(s)
        sc = score(s, r)
        b = baseline_chatbot.evaluate(s)
        rows.append({"scenario": s, "result": r, "score": sc, "baseline": b})
        print(f"{s['id']} {s['category']:16s} {'PASS' if sc['pass'] else 'FAIL'} {r['state']:20s} "
              f"{'; '.join(sc['reasons'])}")
    report.write(rows, elapsed_s=time.time() - t_start)


if __name__ == "__main__":
    main()
