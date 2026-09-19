from __future__ import annotations

import argparse
import copy
import json
import math
import random
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fuelhub.cli import Context
from fuelhub.plan import parse_plan

PLANS = ROOT / "results" / "plans"
RESPONSE_SOURCES = ("B", "E")
RESPONSE_FROM = 2039
PENALTY = 20000.0
SHORTAGE_PENALTY = 200.0
MARGIN_PENALTY = 2000.0

STRATEGIES = {
    "full": {"label": "Earth-New + Lunar-ISRU + ZBO", "investments": ["EARTH_NEW", "LUNAR_ISRU", "ZBO"]},
    "earth": {"label": "Earth-New + ZBO, без Луны", "investments": ["EARTH_NEW", "ZBO"]},
    "lunar": {"label": "Lunar-ISRU + ZBO, без Earth-New", "investments": ["LUNAR_ISRU", "ZBO"]},
}


class Search:
    def __init__(self, ctx, template, strategy, seed, margin=0.0):
        self.ctx = ctx
        self.case = ctx.case
        self.margin = margin
        self.years = list(ctx.case.years)
        self.rng = random.Random(seed)
        self.template = template
        self.investments = [i for i in template["decisions"]["investments"] if i["investment_id"] in STRATEGIES[strategy]["investments"]]
        self.allowed = {i["investment_id"] for i in self.investments}
        self.base = self.cells_from(template)
        for (kind, src, year) in list(self.base):
            if not self.usable(src, year):
                self.base[(kind, src, year)] = 0.0
        self.resp = {}
        self.moves_base = [(k, s, y) for k in ("order", "res") for s in self.case.sources for y in self.years if self.usable(s, y)]
        self.moves_resp = [(k, s, y) for k in ("order", "res") for s in RESPONSE_SOURCES for y in self.years if y >= RESPONSE_FROM]

    def usable(self, src, year):
        if src == "C":
            return "EARTH_NEW" in self.allowed and year >= 2038
        if src == "D":
            return "LUNAR_ISRU" in self.allowed and year >= 2038
        return True

    @staticmethod
    def cells_from(plan):
        cells = {}
        for o in plan["decisions"]["supply_orders"]:
            cells[("order", o["source_id"], o["year"])] = float(o["ordered_t"])
        for r in plan["decisions"]["capacity_reservations"]:
            cells[("res", r["source_id"], r["year"])] = float(r["reserved_capacity_t"])
        return cells

    def plan(self, cells, plan_id, scenario_id):
        orders, res = [], []
        for (kind, src, year), v in sorted(cells.items(), key=lambda kv: (kv[0][2], kv[0][1], kv[0][0])):
            if v <= 0 or (kind == "res" and not self.case.sources[src].needs_reservation):
                continue
            if kind == "order":
                orders.append({"source_id": src, "year": year, "ordered_t": v})
            else:
                res.append({"source_id": src, "year": year, "reserved_capacity_t": v})
        return {
            "plan_id": plan_id,
            "scenario_id": scenario_id,
            "decisions": {
                "supply_orders": orders,
                "capacity_reservations": res,
                "investments": copy.deepcopy(self.investments),
                "inventory_policy": copy.deepcopy(self.template["decisions"]["inventory_policy"]),
            },
        }

    def merged(self):
        cells = dict(self.base)
        cells.update(self.resp)
        return cells

    def run(self, cells, scenario):
        raw = self.plan(cells, "tmp", scenario)
        return self.ctx.run(parse_plan(raw, self.case), scenario)

    def score(self):
        rb = self.run(self.base, "BASE")
        rs = self.run(self.merged(), "MANDATORY_STRESS")
        hard = lambda r: [c for c in r["constraint_checks"] if not c["ok"] and c["severity"] == "hard"]
        hb, hs = hard(rb), hard(rs)
        thin = sum(1 for y in rb["yearly_balance"] if y["reserve_equivalent_days"] < 45 + self.margin)
        pen = PENALTY * (len(hb) + len(hs)) + SHORTAGE_PENALTY * (rb["totals"]["shortage_total_t"] + rs["totals"]["shortage_total_t"]) + MARGIN_PENALTY * thin
        return rb["totals"]["pv_total_mln"] + rs["totals"]["pv_total_mln"] + pen, rb, rs

    def clamp(self, src, v):
        return max(0.0, min(self.case.sources[src].capacity, v))

    def step(self, cells, key):
        kind, src, year = key
        delta = self.rng.choice((-20, -10, -5, 5, 10, 20))
        v = self.clamp(src, cells.get(key, 0.0) + delta)
        cells[key] = v
        other = ("res" if kind == "order" else "order", src, year)
        if self.case.sources[src].needs_reservation:
            if kind == "order" and cells.get(other, 0.0) < v:
                cells[other] = v
            if kind == "res" and cells.get(other, 0.0) > v:
                cells[other] = v
        if kind == "order" and delta < 0 and self.rng.random() < 0.5 and self.case.sources[src].needs_reservation:
            cells[other] = v

    def optimize(self, iters, log):
        best, rb, rs = self.score()
        best_state = (dict(self.base), dict(self.resp))
        cur = best
        for it in range(iters):
            t = 40.0 * (1 - it / iters) + 0.5
            base_backup, resp_backup = dict(self.base), dict(self.resp)
            if self.rng.random() < 0.7:
                self.step(self.base, self.rng.choice(self.moves_base))
            else:
                key = self.rng.choice(self.moves_resp)
                if key not in self.resp:
                    self.resp[key] = self.base.get(key, 0.0)
                self.step(self.resp, key)
            s, rb2, rs2 = self.score()
            if s <= cur or self.rng.random() < math.exp(-(s - cur) / t):
                cur = s
                if s < best - 1e-9:
                    best, rb, rs = s, rb2, rs2
                    best_state = (dict(self.base), dict(self.resp))
                    if log:
                        print(f"  {it:6d}  score {s:9.1f}  BASE pv {rb['totals']['pv_total_mln']:8.0f} {'ok' if rb['feasible'] else 'BAD'}  STRESS pv {rs['totals']['pv_total_mln']:8.0f} {'ok' if rs['feasible'] else 'BAD'}")
            else:
                self.base, self.resp = base_backup, resp_backup
        self.base, self.resp = best_state
        return best, rb, rs

    def clean_response(self):
        self.resp = {k: v for k, v in self.resp.items() if abs(v - self.base.get(k, 0.0)) > 1e-9}


def violations(r):
    return "; ".join(f"{c['rule_id']} {c['year']}" for c in r["constraint_checks"] if not c["ok"] and c["severity"] == "hard") or "нет"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--strategy", choices=list(STRATEGIES) + ["all"], default="all")
    ap.add_argument("--iters", type=int, default=12000)
    ap.add_argument("--seed", type=int, default=2035)
    ap.add_argument("--seeds", type=int, default=3)
    ap.add_argument("--start", default="base-v1")
    ap.add_argument("--margin", type=float, default=0.0, help="запас сверх 45 дней резерва в BASE, дней")
    ap.add_argument("--tag", default="v2", help="префикс идентификаторов планов")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)
    ctx = Context()
    template = json.load(open(PLANS / f"{args.start}.json", encoding="utf-8"))
    names = list(STRATEGIES) if args.strategy == "all" else [args.strategy]
    summary = []
    for name in names:
        print(f"[{name}] {STRATEGIES[name]['label']}, {args.iters} итераций, стартов {args.seeds}, seed {args.seed}, запас резерва {args.margin:.0f} дн", flush=True)
        best = None
        for k in range(args.seeds):
            cand = Search(ctx, template, name, args.seed + k, args.margin)
            score, rb_k, rs_k = cand.optimize(args.iters, not args.quiet)
            print(f"  старт {k + 1}: score {score:.0f}, BASE pv {rb_k['totals']['pv_total_mln']:.0f} {'ok' if rb_k['feasible'] else 'BAD'}, STRESS pv {rs_k['totals']['pv_total_mln']:.0f} {'ok' if rs_k['feasible'] else 'BAD'}", flush=True)
            if best is None or score < best[0]:
                best = (score, cand, rb_k, rs_k)
        _, s, rb, rs = best
        s.clean_response()
        base_id, resp_id = f"{args.tag}-{name}", f"{args.tag}-{name}-response"
        base = s.plan(s.base, base_id, "BASE")
        base["label"] = f"подбор: {STRATEGIES[name]['label']}" + (f", запас резерва {args.margin:.0f} дн" if args.margin else "")
        resp = s.plan(s.merged(), resp_id, "MANDATORY_STRESS")
        resp["label"] = f"ответ на стресс для {base_id}: меняются только Flex и Emergency с {RESPONSE_FROM}"
        json.dump(base, open(PLANS / f"{base_id}.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        json.dump(resp, open(PLANS / f"{resp_id}.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        rb0 = s.run(s.base, "MANDATORY_STRESS")
        row = {
            "strategy": name, "label": STRATEGIES[name]["label"], "base_plan": base_id, "response_plan": resp_id,
            "base_pv": rb["totals"]["pv_total_mln"], "base_feasible": rb["feasible"], "base_violations": violations(rb),
            "stress_no_response_pv": rb0["totals"]["pv_total_mln"], "stress_no_response_feasible": rb0["feasible"], "stress_no_response_shortage": rb0["totals"]["shortage_total_t"], "stress_no_response_violations": violations(rb0),
            "stress_response_pv": rs["totals"]["pv_total_mln"], "stress_response_feasible": rs["feasible"], "stress_response_shortage": rs["totals"]["shortage_total_t"], "stress_response_violations": violations(rs),
            "response_changes": {f"{k[0]} {k[1]} {k[2]}": [s.base.get(k, 0.0), v] for k, v in sorted(s.resp.items(), key=lambda kv: (kv[0][2], kv[0][1]))},
            "capex": rb["totals"]["capex_total_mln"], "seed": args.seed, "iters": args.iters,
        }
        summary.append(row)
        print(f"  итог: BASE pv {row['base_pv']:.0f} ({'исполним' if row['base_feasible'] else row['base_violations']}); "
              f"стресс без ответа pv {row['stress_no_response_pv']:.0f}, дефицит {row['stress_no_response_shortage']:.1f} ({row['stress_no_response_violations']}); "
              f"стресс с ответом pv {row['stress_response_pv']:.0f}, дефицит {row['stress_response_shortage']:.1f} ({'исполним' if row['stress_response_feasible'] else row['stress_response_violations']})")
        print("  ответ:", ", ".join(f"{k}: {a:.0f}→{b:.0f}" for k, (a, b) in row["response_changes"].items()) or "нет изменений")
    out = ROOT / "results" / f"optimize_summary_{args.tag}.json"
    json.dump(summary, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("сводка:", out.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
