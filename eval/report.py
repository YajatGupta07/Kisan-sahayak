"""Write eval/results/report.md and results.json (aggregates + every failed case with the reason)."""
from __future__ import annotations

import json
import statistics
from pathlib import Path

from app import config

OUT = Path(__file__).resolve().parent / "results"


def _pct(n, d):
    return "n/a" if d == 0 else f"{100 * n / d:.0f}% ({n}/{d})"


def write(rows: list[dict], elapsed_s: float = 0.0) -> None:
    OUT.mkdir(exist_ok=True)
    rep = [r for r in rows if "reporting" in r["score"]["checks"]]
    pay = [r for r in rows if "payability" in r["score"]["checks"]]
    amt = [r for r in rows if "amount" in r["score"]["checks"]]
    inj = [r for r in rows if "recovered" in r["score"]["checks"]]
    costs = [r["result"]["cost_inr"] for r in rows]
    mins = [r["result"]["minutes_to_ref"] for r in rep if r["result"]["minutes_to_ref"] is not None]
    base_pay_ok = sum(1 for r in pay if r["baseline"]["payable_answer"] == ("yes" if r["scenario"]["expect"]["payable"] else "no"))
    agg = {
        "scenarios": len(rows),
        "passed": sum(r["score"]["pass"] for r in rows),
        "reporting_completion": _pct(sum(r["score"]["checks"]["reporting"] for r in rep), len(rep)),
        "payability_accuracy": _pct(sum(r["score"]["checks"]["payability"] for r in pay), len(pay)),
        "amount_within_15pct": _pct(sum(r["score"]["checks"]["amount"] for r in amt), len(amt)),
        "failure_recovery": _pct(sum(r["score"]["checks"]["recovered"] for r in inj), len(inj)),
        "mean_cost_inr": round(statistics.mean(costs), 2) if costs else 0,
        "median_minutes_to_ref": statistics.median(mins) if mins else None,
        "baseline_reporting_completion": _pct(0, len(rep)),
        "baseline_payability_accuracy": _pct(base_pay_ok, len(pay)),
        "llm": config.USE_LLM, "elapsed_s": round(elapsed_s, 1),
    }
    (OUT / "results.json").write_text(json.dumps({"aggregate": agg, "rows": rows}, ensure_ascii=False, indent=1,
                                                 default=str))
    fails = [r for r in rows if not r["score"]["pass"]]
    lines = [
        "# Evaluation report", "",
        f"{agg['scenarios']} scenarios · {agg['passed']} passed · NLU: {'LLM + rules' if agg['llm'] else 'rules only'} "
        f"· run time {agg['elapsed_s']} s", "",
        "> All policy, yield and weather data used here is **illustrative** (see `data/`). Insurer writes are mocked. "
        "Payability ground truth is computed independently in `eval/generate.py` from the same illustrative yield "
        "table, so it tests routing, lookup and arithmetic end to end — not agreement with real published payouts.", "",
        "| Metric | Agent | Info-only baseline | Target |", "|---|---|---|---|",
        f"| Reporting completion (valid ref ≤ 72 h, faults injected) | {agg['reporting_completion']} | "
        f"{agg['baseline_reporting_completion']} (cannot file by design) | ≥ 90% |",
        f"| Payability accuracy | {agg['payability_accuracy']} | {agg['baseline_payability_accuracy']} | ≥ 90% |",
        f"| Amount within 15% (payable cases) | {agg['amount_within_15pct']} | n/a | — |",
        f"| Recovery from injected failures | {agg['failure_recovery']} | n/a | ≥ 80% |",
        f"| Cost per case | ₹{agg['mean_cost_inr']} | — | < ₹20 |",
        f"| Median minutes, first message → reference no. (simulated, 3 min per farmer reply) | "
        f"{agg['median_minutes_to_ref']} | — | < 20 |", "",
        "## Failed cases", "",
    ]
    if not fails:
        lines.append("None.")
    for r in fails:
        lines.append(f"- **{r['scenario']['id']}** ({r['scenario']['category']}): {'; '.join(r['score']['reasons'])}")
    lines += ["", "## All cases", "", "| id | category | final state | ref | estimate ₹ | paid ₹ | pass |", "|---|---|---|---|---|---|---|"]
    for r in rows:
        x = r["result"]
        lines.append(f"| {x['id']} | {x['category']} | {x['state']} | {x['reference_no'] or ''} | "
                     f"{x['estimate_inr'] or ''} | {x['paid'] or ''} | {'✅' if r['score']['pass'] else '❌'} |")
    (OUT / "report.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines[:16]))
