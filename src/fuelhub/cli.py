from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import export
from .data import CONFIG_DIR, DATA_DIR, ROOT, load_assumptions, load_case
from .engine import calculate
from .plan import PlanError, load_plan
from .scenario import SCENARIO_DIR, load_scenarios

RESULTS_DIR = ROOT / "results"
COMPARE_METRICS = (
    ("demand_total_t", "yearly_balance"), ("delivered_actual_t", "yearly_balance"), ("losses_t", "yearly_balance"),
    ("served_total_t", "yearly_balance"), ("shortage_total_t", "yearly_balance"), ("shortage_critical_t", "yearly_balance"),
    ("service_level_total", "yearly_balance"), ("service_level_critical", "yearly_balance"),
    ("opening_stock_t", "yearly_balance"), ("closing_stock_t", "yearly_balance"), ("reserve_equivalent_days", "yearly_balance"),
    ("procurement_mln", "financial_breakdown"), ("reservation_mln", "financial_breakdown"), ("holding_mln", "financial_breakdown"),
    ("capex_mln", "financial_breakdown"), ("total_mln", "financial_breakdown"), ("pv_mln", "financial_breakdown"),
)


class Context:
    def __init__(self, data_dir=DATA_DIR, scenario_dir=SCENARIO_DIR, assumptions=CONFIG_DIR / "assumptions.json"):
        self.case = load_case(data_dir)
        self.scenarios = load_scenarios(self.case, scenario_dir)
        self.assumptions = load_assumptions(assumptions)

    def plan(self, path):
        return load_plan(path, self.case, self.scenarios)

    def run(self, plan, scenario_id=None):
        sid = scenario_id or plan.scenario_id
        if sid not in self.scenarios:
            raise PlanError([{"path": "scenario_id", "message": f"неизвестный сценарий {sid}; есть {', '.join(self.scenarios)}"}])
        return calculate(self.case, self.scenarios[sid], plan, self.assumptions)

    def compare(self, plan, scenario_ids) -> dict:
        results = {sid: self.run(plan, sid) for sid in scenario_ids}
        base = scenario_ids[0]
        diff = []
        for year in self.case.years:
            for metric, table in COMPARE_METRICS:
                row = {"year": year, "metric": metric}
                for sid, res in results.items():
                    value = next(r[metric] for r in res[table] if r["year"] == year)
                    row[sid] = value
                    if sid != base:
                        row[f"delta:{sid}"] = round(value - row[base], 6)
                diff.append(row)
        totals = []
        for metric in results[base]["totals"]:
            row = {"metric": metric}
            for sid, res in results.items():
                row[sid] = res["totals"][metric]
                if sid != base and isinstance(row[base], (int, float)) and isinstance(row[sid], (int, float)):
                    row[f"delta:{sid}"] = round(row[sid] - row[base], 6)
            totals.append(row)
        return {
            "plan_id": plan.plan_id,
            "scenarios": scenario_ids,
            "feasible": {sid: res["feasible"] for sid, res in results.items()},
            "violations": {sid: [c for c in res["constraint_checks"] if not c["ok"]] for sid, res in results.items()},
            "totals": totals,
            "yearly": diff,
            "results": results,
        }


def _dump(obj, path):
    if path:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return p
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    return None


def print_summary(res: dict):
    print(f"План {res['plan_id']}, сценарий {res['scenario_id']}: {'исполним' if res['feasible'] else 'НЕ исполним'}")
    print(f"{'год':>5} {'спрос':>7} {'постав.':>8} {'потери':>7} {'выдано':>7} {'дефицит':>8} {'остаток':>8} {'SL общ':>7} {'SL крит':>8} {'резерв,дн':>10}")
    for r in res["yearly_balance"]:
        days = r["reserve_equivalent_days"]
        print(f"{r['year']:>5} {r['demand_total_t']:>7.1f} {r['delivered_actual_t']:>8.1f} {r['losses_t']:>7.2f} {r['served_total_t']:>7.1f} "
              f"{r['shortage_total_t']:>8.1f} {r['closing_stock_t']:>8.1f} {r['service_level_total']:>7.3f} {r['service_level_critical']:>8.3f} "
              f"{days if days == float('inf') else f'{days:.0f}':>10}")
    print(f"{'год':>5} {'закупка':>8} {'бронь':>7} {'хранение':>9} {'OPEX':>6} {'CAPEX':>7} {'итого':>8} {'PV':>8} {'CAPEX накоп.':>13}")
    for f in res["financial_breakdown"]:
        print(f"{f['year']:>5} {f['procurement_mln']:>8.1f} {f['reservation_mln']:>7.1f} {f['holding_mln']:>9.1f} {f['fixed_opex_mln']:>6.0f} "
              f"{f['capex_mln']:>7.0f} {f['total_mln']:>8.1f} {f['pv_mln']:>8.1f} {f['cumulative_capex_mln']:>13.0f}")
    t = res["totals"]
    cpt = t["cost_per_served_t_mln"]
    print(f"Итого {t['total_cost_mln']:.1f}, PV {t['pv_total_mln']:.1f}, CAPEX {t['capex_total_mln']:.0f}, "
          f"дефицит {t['shortage_total_t']:.1f} т, стоимость тонны {cpt if cpt is None else f'{cpt:.2f}'}")
    bad = [c for c in res["constraint_checks"] if not c["ok"]]
    if bad:
        print("Нарушения:")
        for c in bad:
            src = f" [{c['source_id']}]" if c.get("source_id") else ""
            print(f"  {c['severity']:4} {c['rule_id']}{src} {c['year']}: факт {c['actual']:g} {c['operator']} {c['limit']:g}, "
                  f"превышение {c['excess']:g} — {c['reason']}")
    else:
        print("Нарушений нет.")
    for w in res.get("warnings", []):
        print(f"  предупреждение: {w}")


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser(prog="fuelhub", description="Расчётное ядро топливного узла 2035–2040")
    ap.add_argument("--data", default=DATA_DIR, help="папка с CSV организаторов")
    ap.add_argument("--scenarios", default=SCENARIO_DIR, help="папка со сценариями")
    ap.add_argument("--assumptions", default=CONFIG_DIR / "assumptions.json")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("calc", help="посчитать план в сценарии")
    p.add_argument("plan")
    p.add_argument("--scenario")
    p.add_argument("--out", help="куда записать результат JSON")
    p.add_argument("--quiet", action="store_true")

    p = sub.add_parser("validate", help="проверить план без расчёта")
    p.add_argument("plan")

    p = sub.add_parser("compare", help="сравнить сценарии для одного плана")
    p.add_argument("plan")
    p.add_argument("--scenario", nargs="+", default=["BASE", "MANDATORY_STRESS"])
    p.add_argument("--out")

    p = sub.add_parser("export", help="выгрузить результат")
    p.add_argument("plan")
    p.add_argument("--scenario")
    p.add_argument("--format", choices=["csv", "xlsx", "tables", "json"], default="csv")
    p.add_argument("--out", required=True)

    sub.add_parser("scenarios", help="список сценариев")
    sub.add_parser("inputs", help="данные кейса в JSON")

    p = sub.add_parser("serve", help="запустить веб-интерфейс")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8765)

    args = ap.parse_args(argv)
    try:
        ctx = Context(args.data, args.scenarios, args.assumptions)
    except (ValueError, FileNotFoundError, KeyError) as e:
        print(f"ошибка загрузки данных: {e}", file=sys.stderr)
        return 2

    if args.cmd == "serve":
        from .server import serve
        serve(args.host, args.port, ctx)
        return 0
    if args.cmd == "scenarios":
        for s in ctx.scenarios.values():
            print(f"{s.id:18} {s.status:16} {s.label}  ({s.path})")
        return 0
    if args.cmd == "inputs":
        _dump(inputs_payload(ctx), None)
        return 0

    try:
        plan = ctx.plan(args.plan)
        if args.cmd == "validate":
            print(f"план {plan.plan_id} корректен: {len(plan.orders)} заказов, {len(plan.reservations)} броней, "
                  f"{len(plan.investments)} инвестиций, сценарий {plan.scenario_id}")
            return 0
        if args.cmd == "calc":
            res = ctx.run(plan, args.scenario)
            if not args.quiet:
                print_summary(res)
            if args.out:
                _dump(res, args.out)
                print(f"результат записан: {args.out}")
            return 0
        if args.cmd == "compare":
            cmp = ctx.compare(plan, args.scenario)
            for sid in args.scenario:
                print_summary(cmp["results"][sid])
                print()
            print("Итоги по сценариям:")
            for row in cmp["totals"]:
                vals = "  ".join(f"{sid}: {row[sid]}" for sid in args.scenario)
                print(f"  {row['metric']:28} {vals}")
            if args.out:
                _dump(cmp, args.out)
                print(f"сравнение записано: {args.out}")
            return 0
        if args.cmd == "export":
            res = ctx.run(plan, args.scenario)
            if args.format == "csv":
                out = export.write_long_csv(res, args.out)
            elif args.format == "xlsx":
                out = export.write_xlsx(res, args.out)
            elif args.format == "tables":
                out = export.write_tables(res, args.out)[0].parent
            else:
                out = _dump(res, args.out)
            print(f"выгрузка: {out}")
            return 0
    except PlanError as e:
        print("план не принят:", file=sys.stderr)
        for d in e.details:
            print(f"  {d['path']}: {d['message']}", file=sys.stderr)
        return 2
    return 0


def inputs_payload(ctx: Context) -> dict:
    case = ctx.case
    return {
        "data_hash": case.data_hash,
        "years": list(case.years),
        "demand": [d.__dict__ for d in case.demand.values()],
        "sources": [s.__dict__ | {"lead_time_months": s.lead_time_months, "needs_reservation": s.needs_reservation}
                    for s in case.sources.values()],
        "storages": [s.__dict__ for s in case.storages.values()],
        "investments": [i.__dict__ for i in case.investments.values()],
        "constraints": [c.__dict__ for c in case.constraints],
        "scenarios": [s.summary() for s in ctx.scenarios.values()],
        "assumptions": ctx.assumptions.to_list(),
    }


if __name__ == "__main__":
    sys.exit(main())
