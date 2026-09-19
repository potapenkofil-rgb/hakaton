from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import replace
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fuelhub.cli import Context
from fuelhub.data import Assumptions
from fuelhub.plan import PlanError, parse_plan

PLANS = ROOT / "results" / "plans"
COLUMNS = ["plan_id", "scenario_id", "discount_rate", "feasible", "hard_violations", "pv_total_mln", "total_cost_mln", "capex_total_mln",
           "shortage_total_t", "min_reserve_days", "min_service_critical", "cost_per_served_t_mln", "violations"]


def with_rate(ctx, rate):
    if rate is None:
        return ctx
    ctx.assumptions = Assumptions([replace(a, value=rate) if a.name == "discount_rate" else a for a in ctx.assumptions.items], ctx.assumptions.path)
    return ctx


def row(ctx, raw, scenario):
    plan = parse_plan(raw, ctx.case)
    r = ctx.run(plan, scenario)
    bad = [c for c in r["constraint_checks"] if not c["ok"] and c["severity"] == "hard"]
    t = r["totals"]
    return {
        "plan_id": raw["plan_id"], "scenario_id": scenario, "discount_rate": ctx.assumptions["discount_rate"],
        "feasible": r["feasible"], "hard_violations": len(bad),
        "pv_total_mln": round(t["pv_total_mln"], 1), "total_cost_mln": round(t["total_cost_mln"], 1), "capex_total_mln": round(t["capex_total_mln"], 1),
        "shortage_total_t": round(t["shortage_total_t"], 1),
        "min_reserve_days": round(min(min(y["reserve_equivalent_days"], 999) for y in r["yearly_balance"]), 1),
        "min_service_critical": round(t["min_service_level_critical"], 4),
        "cost_per_served_t_mln": round(t["cost_per_served_t_mln"], 3),
        "violations": "; ".join(f"{c['rule_id']} {c['year']}" for c in bad),
    }


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--plans", nargs="*", help="идентификаторы планов из results/plans; по умолчанию все")
    ap.add_argument("--scenarios", nargs="*", default=["BASE", "MANDATORY_STRESS"])
    ap.add_argument("--rates", nargs="*", type=float, help="ставки дисконтирования вместо 0,08 из configs/assumptions.json, например 0 0.04 0.08 0.12")
    ap.add_argument("--out", default=str(ROOT / "results" / "comparison.csv"))
    args = ap.parse_args(argv)
    ctx = Context()
    files = sorted(PLANS.glob("*.json")) if not args.plans else [PLANS / f"{p}.json" for p in args.plans]
    rows, skipped = [], []
    for rate in args.rates or [None]:
        with_rate(ctx, rate)
        for f in files:
            raw = json.load(open(f, encoding="utf-8"))
            for sc in args.scenarios:
                try:
                    rows.append(row(ctx, raw, sc))
                except PlanError as e:
                    skipped.append((f.stem, sc, "; ".join(d["message"] for d in e.details)))
                    break
    with open(args.out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)
    width = max(len(r["plan_id"]) for r in rows) if rows else 8
    print(f"{'план':<{width}} {'сценарий':<16} {'ставка':>6} {'статус':<9} {'PV':>8} {'всего':>8} {'CAPEX':>6} {'дефицит':>8} {'резерв':>7}  нарушения")
    for r in rows:
        print(f"{r['plan_id']:<{width}} {r['scenario_id']:<16} {r['discount_rate']:>6.2f} {'исполним' if r['feasible'] else 'НЕТ':<9} {r['pv_total_mln']:8.0f} {r['total_cost_mln']:8.0f} {r['capex_total_mln']:6.0f} {r['shortage_total_t']:8.1f} {r['min_reserve_days']:7.0f}  {r['violations']}")
    for name, sc, why in skipped:
        print(f"{name:<{width}} пропущен: {why}")
    print("файл:", Path(args.out).relative_to(ROOT) if Path(args.out).is_relative_to(ROOT) else args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
