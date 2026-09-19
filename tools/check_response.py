from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fuelhub.cli import Context
from fuelhub.plan import parse_plan

PLANS = ROOT / "results" / "plans"
ALLOWED_SOURCES = ("B", "E")
ALLOWED_FROM = 2039
STRESS_SEEN = "2038-01"


def cells(plan):
    out = {}
    for o in plan["decisions"]["supply_orders"]:
        out[("заказ", o["source_id"], o["year"])] = float(o["ordered_t"])
    for r in plan["decisions"]["capacity_reservations"]:
        out[("бронь", r["source_id"], r["year"])] = float(r["reserved_capacity_t"])
    return out


def diff(base, resp):
    a, b = cells(base), cells(resp)
    changes = []
    for key in sorted(set(a) | set(b), key=lambda k: (k[2], k[1], k[0])):
        va, vb = a.get(key, 0.0), b.get(key, 0.0)
        if abs(va - vb) > 1e-9:
            changes.append((key, va, vb))
    same_inv = base["decisions"]["investments"] == resp["decisions"]["investments"]
    same_stock = base["decisions"]["inventory_policy"] == resp["decisions"]["inventory_policy"]
    return changes, same_inv, same_stock


def check(base, resp, ctx=None):
    changes, same_inv, same_stock = diff(base, resp)
    problems = []
    if not same_inv:
        problems.append("ответ меняет инвестиции")
    if not same_stock:
        problems.append("ответ меняет стартовый запас")
    for (kind, src, year), va, vb in changes:
        if src not in ALLOWED_SOURCES or year < ALLOWED_FROM:
            problems.append(f"{kind} {src} {year}: {va:.0f}→{vb:.0f} нельзя менять после начала стресса")
    order_by = {}
    if ctx is not None:
        r = ctx.run(parse_plan(resp, ctx.case), "MANDATORY_STRESS")
        for s in r["source_schedule"]:
            order_by[(s["source_id"], s["year"])] = s["order_by"]
        for (kind, src, year), va, vb in changes:
            ob = order_by.get((src, year), "")
            if kind == "заказ" and ob and ob < STRESS_SEEN:
                problems.append(f"заказ {src} {year} надо разместить до {ob}, раньше начала стресса {STRESS_SEEN}")
    return changes, problems, order_by


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("base")
    ap.add_argument("response")
    args = ap.parse_args(argv)
    ctx = Context()
    base = json.load(open(PLANS / f"{args.base}.json", encoding="utf-8"))
    resp = json.load(open(PLANS / f"{args.response}.json", encoding="utf-8"))
    changes, problems, order_by = check(base, resp, ctx)
    print(f"ответ {args.response} относительно {args.base}: изменений {len(changes)}")
    for (kind, src, year), va, vb in changes:
        print(f"  {year} {src} {kind}: {va:.0f} → {vb:.0f}   заказать до {order_by.get((src, year), '—')}")
    if problems:
        print("нарушения правила реакции:")
        for p in problems:
            print("  -", p)
        return 1
    print("правило реакции соблюдено: меняются только Flex и Emergency с 2039, все заказы размещаются после начала стресса")
    return 0


if __name__ == "__main__":
    sys.exit(main())
