from __future__ import annotations

import argparse
import copy
import csv
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fuelhub.cli import Context
from fuelhub.plan import parse_plan

PLANS = ROOT / "results" / "plans"
REGISTER = ROOT / "configs" / "risks.json"


def apply_patch(plan, patch):
    p = copy.deepcopy(plan)
    if not patch:
        return p
    d = p["decisions"]
    for kind, key, field in (("orders", "supply_orders", "ordered_t"), ("reservations", "capacity_reservations", "reserved_capacity_t")):
        for src, years in (patch.get(kind) or {}).items():
            for year, value in years.items():
                year = int(year)
                rows = [r for r in d[key] if r["source_id"] == src and r["year"] == year]
                if rows:
                    rows[0][field] = float(value)
                else:
                    d[key].append({"source_id": src, "year": year, field: float(value)})
        d[key] = [r for r in d[key] if r[field] > 0]
    for inv_id, fields in (patch.get("investments") or {}).items():
        rows = [i for i in d["investments"] if i["investment_id"] == inv_id]
        if fields is None:
            d["investments"] = [i for i in d["investments"] if i["investment_id"] != inv_id]
        elif rows:
            rows[0].update(fields)
        else:
            d["investments"].append({"investment_id": inv_id, **fields})
    if patch.get("inventory"):
        d["inventory_policy"].update(patch["inventory"])
    return p


def summary(r):
    bad = [c for c in r["constraint_checks"] if not c["ok"] and c["severity"] == "hard"]
    return {
        "feasible": r["feasible"],
        "pv": round(r["totals"]["pv_total_mln"], 1),
        "total": round(r["totals"]["total_cost_mln"], 1),
        "shortage": round(r["totals"]["shortage_total_t"], 1),
        "min_reserve": round(min(min(y["reserve_equivalent_days"], 999) for y in r["yearly_balance"]), 1),
        "losses": round(r["totals"]["losses_t"], 1),
        "top_up": round(sum(f["take_or_pay_topup_mln"] for f in r["financial_breakdown"]), 1),
        "overflow": round(sum(y["overflow_t"] for y in r["yearly_balance"]), 1),
        "violations": "; ".join(f"{c['rule_id']} {c['year']}" for c in bad),
    }


def assess(reg, risk, contexts):
    data_dir = risk.get("data_dir")
    ctx0 = contexts.setdefault("", Context())
    ctx1 = contexts.setdefault(data_dir, Context(ROOT / data_dir)) if data_dir else ctx0
    plan_id = risk.get("plan_id") or reg["plan_id"]
    plan = json.load(open(PLANS / f"{plan_id}.json", encoding="utf-8"))
    base_sc = risk.get("base_scenario", "BASE")
    run = lambda ctx, p, sc: summary(ctx.run(parse_plan(p, ctx.case), sc))
    baseline = run(ctx0, plan, base_sc)
    struck = apply_patch(plan, risk.get("plan_patch"))
    hit = run(ctx1, struck, risk["scenario_id"])
    m = risk.get("measure") or {}
    prep_cost = run(ctx0, apply_patch(plan, m.get("prep")), base_sc)
    after = run(ctx1, apply_patch(apply_patch(struck, m.get("prep")), m.get("response")), risk["scenario_id"])
    return {
        "id": risk["id"], "title": risk["title"], "plan_id": plan_id, "scenario_id": risk["scenario_id"], "base_scenario": base_sc,
        "data_dir": data_dir or "data",
        "baseline": baseline, "hit": hit,
        "measure": m.get("title", "нет"), "measure_cost_pv": round(prep_cost["pv"] - baseline["pv"], 1),
        "prepared_feasible": prep_cost["feasible"], "after": after,
        "effect_pv": round(hit["pv"] - baseline["pv"], 1), "after_pv_delta": round(after["pv"] - baseline["pv"], 1),
    }


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--register", default=str(REGISTER))
    ap.add_argument("--only", nargs="*")
    args = ap.parse_args(argv)
    reg = json.load(open(args.register, encoding="utf-8"))
    contexts = {}
    rows = []
    for risk in reg["risks"]:
        if args.only and risk["id"] not in args.only:
            continue
        rows.append(assess(reg, risk, contexts))
    print(f"план {reg['plan_id']}, реестр {Path(args.register).name}, рисков {len(rows)}\n")
    for r in rows:
        h, a, b = r["hit"], r["after"], r["baseline"]
        print(f"{r['id']} {r['title']}  [{r['scenario_id']}, {r['data_dir']}]")
        print(f"   без мер : {'исполним' if h['feasible'] else 'НЕТ'}  PV {h['pv']:.0f} ({r['effect_pv']:+.0f})  дефицит {h['shortage']:.1f} т  резерв {h['min_reserve']:.0f} дн  переполнение {h['overflow']:.1f} т  take-or-pay {h['top_up']:.0f}  {h['violations']}")
        print(f"   мера    : {r['measure']}  цена в {r['base_scenario']}: {r['measure_cost_pv']:+.0f} PV{'' if r['prepared_feasible'] else '  (ВНИМАНИЕ: план с мерой не исполним в базе)'}")
        print(f"   остаток : {'исполним' if a['feasible'] else 'НЕТ'}  PV {a['pv']:.0f} ({r['after_pv_delta']:+.0f})  дефицит {a['shortage']:.1f} т  резерв {a['min_reserve']:.0f} дн  переполнение {a['overflow']:.1f} т  {a['violations']}")
    out_json = ROOT / "results" / "risks_assessment.json"
    json.dump(rows, open(out_json, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    out_csv = ROOT / "results" / "risks_assessment.csv"
    with open(out_csv, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["id", "title", "scenario_id", "data_dir", "baseline_pv", "hit_feasible", "hit_pv", "effect_pv", "hit_shortage_t", "hit_min_reserve_days", "hit_violations",
                    "measure", "measure_cost_pv", "after_feasible", "after_pv", "after_shortage_t", "after_min_reserve_days", "after_violations"])
        for r in rows:
            h, a = r["hit"], r["after"]
            w.writerow([r["id"], r["title"], r["scenario_id"], r["data_dir"], r["baseline"]["pv"], h["feasible"], h["pv"], r["effect_pv"], h["shortage"], h["min_reserve"], h["violations"],
                        r["measure"], r["measure_cost_pv"], a["feasible"], a["pv"], a["shortage"], a["min_reserve"], a["violations"]])
    print(f"\nфайлы: {out_json.relative_to(ROOT)}, {out_csv.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
