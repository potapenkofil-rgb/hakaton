from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fuelhub.cli import Context
from fuelhub.engine import calculate
from fuelhub.plan import parse_plan
from fuelhub.scenario import SCENARIO_DIR, parse_yaml, scenario_from_dict

PLANS = ROOT / "results" / "plans"
SHOCK_YEARS = (2038, 2039, 2040)
STEPS = {
    "demand": [round(1.0 + 0.05 * i, 2) for i in range(0, 9)],
    "isru": [round(1.0 - 0.05 * i, 2) for i in range(0, 13)],
    "price": [round(1.0 + 0.05 * i, 2) for i in range(0, 13)],
    "flex_delivery": [round(1.0 - 0.1 * i, 2) for i in range(0, 8)],
}
LABELS = {
    "demand": "спрос 2038–2040, множитель",
    "isru": "поставка Lunar-ISRU 2038–2040, доля плана",
    "price": "цена Earth-Core и Earth-Flex 2038–2040, множитель",
    "flex_delivery": "поставка Earth-Flex 2038–2040, доля плана",
}


def variant(raw, kind, value):
    r = json.loads(json.dumps(raw))
    r["scenario_id"] = f"SENS_{kind.upper()}_{value}"
    r["constraint_profile"] = raw.get("constraint_profile") or raw["scenario_id"]
    r["status"] = "TEAM_ASSUMPTION"
    r["label_ru"] = f"{raw.get('label_ru', raw['scenario_id'])}: {LABELS[kind]} = {value}"
    if kind == "demand":
        for key in ("demand_multiplier", "critical_demand_multiplier"):
            m = r.setdefault(key, {})
            for y in SHOCK_YEARS:
                m[str(y)] = round(float(m.get(str(y), m.get(y, m.get("default", 1.0)))) * value, 4)
    elif kind == "isru":
        m = r.setdefault("actual_delivery_share", {}).setdefault("Lunar-ISRU", {})
        for y in SHOCK_YEARS:
            m[str(y)] = round(float(m.get(str(y), m.get(y, m.get("default", 1.0)))) * value, 4)
    elif kind == "flex_delivery":
        m = r.setdefault("actual_delivery_share", {}).setdefault("Earth-Flex", {})
        for y in SHOCK_YEARS:
            m[str(y)] = round(float(m.get(str(y), m.get(y, m.get("default", 1.0)))) * value, 4)
    elif kind == "price":
        for name in ("Earth-Core", "Earth-Flex"):
            m = r.setdefault("variable_price_multiplier", {}).setdefault(name, {})
            for y in SHOCK_YEARS:
                m[str(y)] = round(float(m.get(str(y), m.get(y, m.get("default", 1.0)))) * value, 4)
    for key in ("demand_multiplier", "critical_demand_multiplier"):
        if isinstance(r.get(key), dict):
            r[key] = {str(k): v for k, v in r[key].items()}
    for key in ("actual_delivery_share", "variable_price_multiplier"):
        if isinstance(r.get(key), dict):
            r[key] = {s: ({str(k): v for k, v in m.items()} if isinstance(m, dict) else m) for s, m in r[key].items()}
    return r


def run(ctx, plan, raw):
    sc = scenario_from_dict(raw, ctx.case)
    r = calculate(ctx.case, sc, plan, ctx.assumptions)
    bad = [c for c in r["constraint_checks"] if not c["ok"] and c["severity"] == "hard"]
    return {
        "feasible": r["feasible"], "hard_violations": len(bad),
        "pv_total_mln": round(r["totals"]["pv_total_mln"], 1), "shortage_total_t": round(r["totals"]["shortage_total_t"], 1),
        "min_reserve_days": round(min(min(y["reserve_equivalent_days"], 999) for y in r["yearly_balance"]), 1),
        "first_violation": f"{bad[0]['rule_id']} {bad[0]['year']}" if bad else "",
    }


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("plan")
    ap.add_argument("--scenario", default="BASE", help="BASE или MANDATORY_STRESS как отправная точка")
    ap.add_argument("--kinds", nargs="*", default=list(STEPS))
    ap.add_argument("--against", help="план-альтернатива: печатает его PV рядом и порог, где он становится дешевле")
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)
    ctx = Context()
    plan_raw = json.load(open(PLANS / f"{args.plan}.json", encoding="utf-8"))
    plan = parse_plan(plan_raw, ctx.case)
    other = parse_plan(json.load(open(PLANS / f"{args.against}.json", encoding="utf-8")), ctx.case) if args.against else None
    file = {"BASE": "base.yaml", "MANDATORY_STRESS": "mandatory_stress.yaml"}[args.scenario]
    base_raw = parse_yaml((SCENARIO_DIR / file).read_text(encoding="utf-8"))
    rows = []
    print(f"план {args.plan}, отправная точка {args.scenario}")
    for kind in args.kinds:
        boundary = None
        cheaper = None
        print(f"\n{LABELS[kind]}")
        for value in STEPS[kind]:
            sc = variant(base_raw, kind, value)
            res = run(ctx, plan, sc)
            row = {"plan_id": args.plan, "scenario_base": args.scenario, "parameter": kind, "value": value, **res}
            mark = "исполним" if res["feasible"] else f"НЕТ: {res['first_violation']}"
            tail = ""
            if other:
                alt = run(ctx, other, sc)
                row[f"pv_{args.against}"] = alt["pv_total_mln"]
                row[f"feasible_{args.against}"] = alt["feasible"]
                tail = f"  {args.against}: PV {alt['pv_total_mln']:8.0f} {'исполним' if alt['feasible'] else 'НЕТ'}"
                if cheaper is None and alt["feasible"] and alt["pv_total_mln"] < res["pv_total_mln"]:
                    cheaper = value
            rows.append(row)
            print(f"  {value:5.2f}  PV {res['pv_total_mln']:8.0f}  дефицит {res['shortage_total_t']:6.1f}  резерв {res['min_reserve_days']:4.0f} дн  {mark}{tail}")
            if boundary is None and not res["feasible"]:
                boundary = (value, res["first_violation"])
        print("  граница:", f"{boundary[0]} ({boundary[1]})" if boundary else "в проверенном диапазоне нарушений нет")
        if other:
            print(f"  {args.against} дешевле:", f"с {cheaper}" if cheaper is not None else "нигде в проверенном диапазоне")
    out = Path(args.out) if args.out else ROOT / "results" / f"sensitivity_{args.plan}_{args.scenario}{'_vs_' + args.against if args.against else ''}.csv"
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print("\nфайл:", out.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
