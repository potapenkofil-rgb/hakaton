import json
import random

import pytest

from fuelhub.export import long_rows

from conftest import YEARS, make_plan, run


def random_plan(rnd: random.Random, case) -> dict:
    orders, reservations = {}, {}
    for sid, s in case.sources.items():
        orders[sid], reservations[sid] = {}, {}
        for y in YEARS:
            if rnd.random() < 0.6:
                reserved = rnd.uniform(0, s.capacity * 1.1)
                reservations[sid][y] = round(reserved, 2)
                orders[sid][y] = round(rnd.uniform(0, reserved * 1.2), 2)
    investments = []
    if rnd.random() < 0.6:
        oy = rnd.choice(YEARS[:-1])
        investments.append({"investment_id": "EARTH_NEW", "option_year": oy, "exercise_year": rnd.choice([y for y in YEARS if y >= oy])})
    if rnd.random() < 0.6:
        n = rnd.randint(1, 3)
        investments.append({"investment_id": "LUNAR_ISRU", "financing_years": sorted(rnd.sample(YEARS, n))})
    if rnd.random() < 0.6:
        investments.append({"investment_id": "ZBO", "year": rnd.choice(YEARS)})
    inv = {"initial_stock_t": round(rnd.uniform(0, 80), 2), "initial_stock_source_id": rnd.choice(["A", "B"]), "storage_id": "BASE"}
    return make_plan(orders=orders, reservations=reservations, investments=investments, inventory=inv, plan_id=f"rnd-{rnd.random():.6f}")


def check_invariants(res, case, scenario):
    rate = {"BASE": 0.045, "ZBO": 0.012}
    prev_close = None
    for r in res["yearly_balance"]:
        assert r["closing_stock_t"] >= -1e-9
        assert r["closing_stock_t"] == pytest.approx(r["opening_stock_t"] + r["delivered_actual_t"] - r["losses_t"] - r["served_total_t"], abs=1e-5)
        assert r["losses_t"] == pytest.approx(r["delivered_actual_t"] * rate[r["storage_id"]], abs=1e-6)
        assert 0 <= r["service_level_total"] <= 1 + 1e-9 and 0 <= r["service_level_critical"] <= 1 + 1e-9
        assert r["served_critical_t"] <= r["served_total_t"] + 1e-9
        assert r["shortage_total_t"] >= r["shortage_critical_t"] - 1e-9
        assert r["demand_total_t"] == pytest.approx(scenario.demand(case, r["year"])[0])
        if prev_close is not None:
            assert r["opening_stock_t"] == pytest.approx(prev_close)
        prev_close = r["closing_stock_t"]
    for s in res["source_schedule"]:
        src = case.sources[s["source_id"]]
        assert s["delivered_plan_t"] <= s["capacity_available_t"] + 1e-6
        assert s["delivered_plan_t"] <= s["ordered_t"] + 1e-6
        if src.needs_reservation:
            assert s["delivered_plan_t"] <= s["reserved_capacity_t"] * s["available_months"] / 12 + 1e-6
        assert s["delivered_actual_t"] == pytest.approx(s["delivered_plan_t"] * scenario.delivered_share(src.id, s["year"]))
        assert s["payable_volume_t"] >= s["delivered_actual_t"] - 1e-9
        assert s["variable_payment_mln"] == pytest.approx(s["payable_volume_t"] * s["price_mln_per_t"])
        assert s["reservation_payment_mln"] == pytest.approx(src.reservation_rate * s["reserved_capacity_t"] * s["available_months"] / 12)
        if not s["available"]:
            assert s["delivered_actual_t"] == 0 and s["reservation_payment_mln"] == 0
    for f in res["financial_breakdown"]:
        parts = f["procurement_mln"] + f["reservation_mln"] + f["holding_mln"] + f["fixed_opex_mln"] + f["capex_mln"] + f["initial_stock_mln"]
        assert f["total_mln"] == pytest.approx(parts, abs=1e-5)
        assert f["pv_mln"] == pytest.approx(f["total_mln"] * f["discount_factor"], rel=1e-6)
    assert res["totals"]["capex_total_mln"] == pytest.approx(sum(f["capex_mln"] for f in res["financial_breakdown"]))
    hard_failed = [c for c in res["constraint_checks"] if c["severity"] == "hard" and not c["ok"]]
    assert res["feasible"] == (not hard_failed)
    for c in res["constraint_checks"]:
        assert c["ok"] == (c["excess"] <= 1e-9)
        assert c["year"] in YEARS
    text = json.dumps(res)
    assert "Infinity" not in text and "NaN" not in text
    for row in long_rows(res):
        assert isinstance(row["value"], (int, float))


@pytest.mark.parametrize("seed", range(60))
def test_random_plan_invariants(case, scenarios, assumptions, seed):
    rnd = random.Random(seed)
    plan = random_plan(rnd, case)
    for sid in ("BASE", "MANDATORY_STRESS"):
        res = run(case, scenarios, assumptions, plan, sid)
        check_invariants(res, case, scenarios[sid])


def test_random_plans_repeatable(case, scenarios, assumptions):
    plan = random_plan(random.Random(7), case)
    a = json.dumps(run(case, scenarios, assumptions, plan, "MANDATORY_STRESS"), sort_keys=True)
    b = json.dumps(run(case, scenarios, assumptions, plan, "MANDATORY_STRESS"), sort_keys=True)
    assert a == b


def test_stress_never_cheaper_on_procurement_per_tonne(case, scenarios, assumptions):
    for seed in range(20):
        plan = random_plan(random.Random(100 + seed), case)
        base = run(case, scenarios, assumptions, plan, "BASE")
        stress = run(case, scenarios, assumptions, plan, "MANDATORY_STRESS")
        for y in (2038, 2039):
            for sid in ("A", "B"):
                b = next(s for s in base["source_schedule"] if s["year"] == y and s["source_id"] == sid)
                s = next(s for s in stress["source_schedule"] if s["year"] == y and s["source_id"] == sid)
                assert s["price_mln_per_t"] == pytest.approx(b["price_mln_per_t"] * 1.25)
                assert s["reservation_payment_mln"] == pytest.approx(b["reservation_payment_mln"])
        assert [f["capex_mln"] for f in stress["financial_breakdown"]] == [f["capex_mln"] for f in base["financial_breakdown"]]
        for y in YEARS:
            bd = next(r for r in base["yearly_balance"] if r["year"] == y)["demand_total_t"]
            sd = next(r for r in stress["yearly_balance"] if r["year"] == y)["demand_total_t"]
            assert sd == pytest.approx(bd * (1.15 if y >= 2038 else 1.0))
