import json
import math

import pytest

from fuelhub import calculate, parse_plan
from fuelhub.scenario import scenario_from_dict

from conftest import YEARS, failed, make_plan, run, with_assumptions, year_row


@pytest.fixture(scope="module")
def base(case, scenarios, assumptions, base_plan_dict):
    return run(case, scenarios, assumptions, base_plan_dict, "BASE")


@pytest.fixture(scope="module")
def stress(case, scenarios, assumptions, base_plan_dict):
    return run(case, scenarios, assumptions, base_plan_dict, "MANDATORY_STRESS")


def full_plan(**over):
    orders = {"A": {y: 90 for y in YEARS}, "B": {y: 10 for y in YEARS}}
    reservations = {"A": {y: 100 for y in YEARS}, "B": {y: 20 for y in YEARS}}
    p = make_plan(orders=orders, reservations=reservations, inventory={"initial_stock_t": 20, "initial_stock_cost_mln": 178})
    for k, v in over.items():
        p["decisions"][k] = v
    return p


def test_base_plan_feasible(base):
    assert base["feasible"] is True
    assert failed(base) == []
    assert base["scenario_id"] == "BASE" and base["plan_id"] == "base-v1"


def test_yearly_balance_identity(base, stress):
    for res in (base, stress):
        for r in res["yearly_balance"]:
            assert r["closing_stock_t"] == pytest.approx(r["opening_stock_t"] + r["delivered_actual_t"] - r["losses_t"] - r["served_total_t"], abs=1e-6)
            assert r["closing_stock_t"] >= -1e-9
            assert r["shortage_total_t"] == pytest.approx(max(0.0, r["demand_total_t"] - r["served_total_t"]), abs=1e-6)
            assert r["served_critical_t"] <= r["served_total_t"] + 1e-9
            assert r["demand_critical_t"] <= r["demand_total_t"] + 1e-9
            assert r["service_level_total"] == pytest.approx(r["served_total_t"] / r["demand_total_t"])
            assert r["service_level_critical"] == pytest.approx(r["served_critical_t"] / r["demand_critical_t"])


def test_years_chain(base):
    rows = base["yearly_balance"]
    for prev, nxt in zip(rows, rows[1:]):
        assert nxt["opening_stock_t"] == pytest.approx(prev["closing_stock_t"])
    assert rows[0]["opening_stock_t"] == 15


def test_monthly_balance_identity(base):
    for m in base["monthly_trace"]:
        assert m["closing_t"] == pytest.approx(m["opening_t"] + m["inflow_t"] - m["losses_t"] - m["served_t"], abs=1e-5)
        assert m["closing_t"] >= -1e-9
        assert m["losses_t"] == pytest.approx(m["inflow_t"] * (0.045 if m["storage_id"] == "BASE" else 0.012))
    assert len(base["monthly_trace"]) == 72
    assert sum(m["served_t"] for m in base["monthly_trace"] if m["year"] == 2037) == pytest.approx(190)


def test_losses_once_from_inflow(base):
    for r in base["yearly_balance"]:
        rate = 0.045 if r["storage_id"] == "BASE" else 0.012
        assert r["losses_t"] == pytest.approx(r["delivered_actual_t"] * rate)
        assert r["loss_share"] == pytest.approx(rate)


def test_base_has_no_reliability_multiplier(base):
    for s in base["source_schedule"]:
        assert s["delivered_actual_t"] == pytest.approx(s["delivered_plan_t"])
        assert s["delivery_share"] == 1.0
    assert year_row(base, "source_schedule", 2035, source_id="A")["reliability"] == 0.96


def test_earth_new_reliability_first_year_then_later(base):
    assert year_row(base, "source_schedule", 2038, source_id="C")["reliability"] == 0.88
    assert year_row(base, "source_schedule", 2039, source_id="C")["reliability"] == 0.94
    assert year_row(base, "source_schedule", 2038, source_id="D")["reliability"] == 0.78
    assert year_row(base, "source_schedule", 2040, source_id="D")["reliability"] == 0.93


def test_take_or_pay_inside_max(base):
    c = year_row(base, "source_schedule", 2038, source_id="C")
    assert c["reserved_capacity_t"] == 130 and c["ordered_t"] == 50
    assert c["payable_volume_t"] == pytest.approx(65)
    assert c["take_or_pay_topup_t"] == pytest.approx(15)
    assert c["variable_payment_mln"] == pytest.approx(65 * 7.1)
    assert c["reservation_payment_mln"] == pytest.approx(130 * 0.3)
    fin = year_row(base, "financial_breakdown", 2038)
    assert fin["procurement_mln"] == pytest.approx(sum(s["variable_payment_mln"] for s in base["source_schedule"] if s["year"] == 2038))
    assert fin["take_or_pay_topup_mln"] == pytest.approx(15 * 7.1)


def test_reservation_payment_full_year(base):
    a = year_row(base, "source_schedule", 2036, source_id="A")
    assert a["reservation_payment_mln"] == pytest.approx(150 * 0.45)


def test_financial_breakdown_sums(base):
    for f in base["financial_breakdown"]:
        assert f["total_mln"] == pytest.approx(f["procurement_mln"] + f["reservation_mln"] + f["holding_mln"]
                                               + f["fixed_opex_mln"] + f["capex_mln"] + f["initial_stock_mln"])
        assert f["pv_mln"] == pytest.approx(f["total_mln"] / 1.08 ** (f["year"] - 2035))
    t = base["totals"]
    assert t["total_cost_mln"] == pytest.approx(sum(f["total_mln"] for f in base["financial_breakdown"]))
    assert t["pv_total_mln"] == pytest.approx(sum(f["pv_mln"] for f in base["financial_breakdown"]))
    assert t["cost_per_served_t_mln"] == pytest.approx(t["total_cost_mln"] / t["served_total_t"])
    assert t["discount_rate"] == 0.08 and t["discount_base_year"] == 2035


def test_capex_schedule_earth_new_isru_zbo(base):
    fin = {f["year"]: f for f in base["financial_breakdown"]}
    assert fin[2035]["capex_mln"] == 90
    assert fin[2036]["capex_mln"] == pytest.approx(270 + 625)
    assert fin[2037]["capex_mln"] == pytest.approx(625 + 180)
    assert fin[2038]["capex_mln"] == 0
    assert fin[2037]["cumulative_capex_mln"] == pytest.approx(1790)
    assert base["totals"]["capex_total_mln"] == pytest.approx(1790)
    assert fin[2035]["initial_stock_mln"] == 133.5 and fin[2036]["initial_stock_mln"] == 0


def test_fixed_opex_isru_and_zbo(base):
    fin = {f["year"]: f for f in base["financial_breakdown"]}
    assert fin[2036]["fixed_opex_mln"] == 0
    assert fin[2037]["fixed_opex_mln"] == 12
    assert fin[2038]["fixed_opex_mln"] == 82 and fin[2040]["fixed_opex_mln"] == 82


def test_holding_cost_monthly_average(base):
    for y in YEARS:
        months = [m for m in base["monthly_trace"] if m["year"] == y]
        expected = sum((m["opening_t"] + m["closing_t"]) / 2 * 0.72 / 12 for m in months)
        assert year_row(base, "financial_breakdown", y)["holding_mln"] == pytest.approx(expected)


def test_zbo_switches_capacity_and_losses(base):
    assert year_row(base, "yearly_balance", 2036)["storage_capacity_t"] == 70
    assert year_row(base, "yearly_balance", 2037)["storage_capacity_t"] == 120
    assert year_row(base, "yearly_balance", 2037)["storage_id"] == "ZBO"
    assert year_row(base, "yearly_balance", 2037)["loss_share"] == pytest.approx(0.012)


def test_isru_available_from_march_2038(base):
    d = year_row(base, "source_schedule", 2038, source_id="D")
    assert d["available_from"] == "2038-03" and d["available_months"] == 10
    assert d["capacity_available_t"] == pytest.approx(100)
    assert year_row(base, "source_schedule", 2037, source_id="D")["available"] is False
    assert year_row(base, "source_schedule", 2039, source_id="D")["available_months"] == 12


def test_earth_new_available_from_2038(base):
    assert year_row(base, "source_schedule", 2037, source_id="C")["available"] is False
    c = year_row(base, "source_schedule", 2038, source_id="C")
    assert c["available_from"] == "2038-01"
    assert c["order_by"] == "2036-01"


def test_order_by_reflects_lead_time(base):
    assert year_row(base, "source_schedule", 2036, source_id="A")["order_by"] == "2035-01"
    assert year_row(base, "source_schedule", 2036, source_id="B")["order_by"] == "2035-09"
    assert "заранее" in year_row(base, "source_schedule", 2035, source_id="A")["order_by"]
    assert year_row(base, "source_schedule", 2036, source_id="E")["lead_time"] == "6 week"


def test_reserve_check_at_start_of_year(base):
    for r in base["yearly_balance"]:
        assert r["reserve_required_t"] == pytest.approx(r["demand_total_t"] * 45 / 365)
        assert r["reserve_days_at_start"] == pytest.approx(r["opening_stock_t"] / r["demand_total_t"] * 365)
        assert r["reserve_equivalent_days"] >= 45


def test_all_constraint_rows_present(base):
    ids = {c["rule_id"] for c in base["constraint_checks"]}
    assert ids == {"BASE_CRITICAL_SERVICE", "BASE_TOTAL_SERVICE", "CAPEX_2037", "CAPEX_2040", "RESERVE_45D", "EMERGENCY_BASE_STREAK"}
    per_year = [c for c in base["constraint_checks"] if c["rule_id"] == "RESERVE_45D"]
    assert [c["year"] for c in per_year] == list(YEARS)
    for c in base["constraint_checks"]:
        assert set(c) >= {"rule_id", "year", "metric", "operator", "limit", "actual", "excess", "ok", "severity", "reason"}


def test_stress_demand_applied_only_from_2038(base, stress):
    for y in YEARS:
        b, s = year_row(base, "yearly_balance", y), year_row(stress, "yearly_balance", y)
        k = 1.15 if y >= 2038 else 1.0
        assert s["demand_total_t"] == pytest.approx(b["demand_total_t"] * k)
        assert s["demand_critical_t"] == pytest.approx(b["demand_critical_t"] * k)


def test_stress_prices_only_core_flex_2038_2039(base, stress):
    for s in stress["source_schedule"]:
        b = year_row(base, "source_schedule", s["year"], source_id=s["source_id"])
        k = 1.25 if s["source_id"] in ("A", "B") and s["year"] in (2038, 2039) else 1.0
        assert s["price_mln_per_t"] == pytest.approx(b["price_mln_per_t"] * k)
        assert s["reservation_payment_mln"] == pytest.approx(b["reservation_payment_mln"])
    assert [f["capex_mln"] for f in stress["financial_breakdown"]] == [f["capex_mln"] for f in base["financial_breakdown"]]


def test_stress_isru_delivery_share_not_times_reliability(stress):
    d38 = year_row(stress, "source_schedule", 2038, source_id="D")
    d39 = year_row(stress, "source_schedule", 2039, source_id="D")
    d40 = year_row(stress, "source_schedule", 2040, source_id="D")
    assert d38["delivered_actual_t"] == pytest.approx(d38["delivered_plan_t"] * 0.55)
    assert d39["delivered_actual_t"] == pytest.approx(d39["delivered_plan_t"] * 0.75)
    assert d40["delivered_actual_t"] == pytest.approx(d40["delivered_plan_t"])
    assert d38["variable_payment_mln"] == pytest.approx(d38["delivered_actual_t"] * 3.0)
    assert d38["reliability"] == 0.78


def test_stress_loss_limit_rows_only_from_2038(stress, base):
    rows = [c for c in stress["constraint_checks"] if c["rule_id"] == "STRESS_LOSS_LIMIT"]
    assert [c["year"] for c in rows] == [2038, 2039, 2040]
    assert all(c["ok"] and c["severity"] == "hard" for c in rows)
    assert not [c for c in base["constraint_checks"] if c["rule_id"] == "STRESS_LOSS_LIMIT"]


def test_stress_base_service_rows_are_info(stress):
    rows = [c for c in stress["constraint_checks"] if c["rule_id"] == "BASE_TOTAL_SERVICE"]
    assert rows and all(c["severity"] == "info" for c in rows)
    bad = [c for c in rows if not c["ok"]]
    assert [c["year"] for c in bad] == [2039, 2040]
    assert bad[0]["excess"] == pytest.approx(0.97 - bad[0]["actual"])


def test_stress_base_plan_infeasible_because_of_reserve(stress):
    assert stress["feasible"] is False
    hard = {(c["rule_id"], c["year"]) for c in failed(stress) if c["severity"] == "hard"}
    assert hard == {("RESERVE_45D", 2039), ("RESERVE_45D", 2040)}
    assert stress["totals"]["shortage_total_t"] > 0


def test_stress_loss_limit_fails_with_base_storage(case, scenarios, assumptions):
    res = run(case, scenarios, assumptions, full_plan(), "MANDATORY_STRESS")
    bad = failed(res, "STRESS_LOSS_LIMIT")
    assert [c["year"] for c in bad] == [2038, 2039, 2040]
    assert bad[0]["actual"] == pytest.approx(0.045) and bad[0]["excess"] == pytest.approx(0.025)


def test_capacity_exceeded_clips_delivery(case, scenarios, assumptions):
    p = make_plan(orders={"A": {2035: 200}}, reservations={"A": {2035: 190}})
    res = run(case, scenarios, assumptions, p)
    bad = failed(res, "CAPACITY_EXCEEDED")
    assert bad[0]["excess"] == pytest.approx(10) and bad[0]["source_id"] == "A" and bad[0]["year"] == 2035
    assert year_row(res, "source_schedule", 2035, source_id="A")["delivered_actual_t"] == pytest.approx(190)


def test_order_above_reservation(case, scenarios, assumptions):
    p = make_plan(orders={"A": {2035: 120}}, reservations={"A": {2035: 100}})
    res = run(case, scenarios, assumptions, p)
    bad = failed(res, "ORDER_EXCEEDS_RESERVATION")
    assert bad[0]["excess"] == pytest.approx(20)
    assert year_row(res, "source_schedule", 2035, source_id="A")["delivered_actual_t"] == pytest.approx(100)


def test_reservation_above_capacity(case, scenarios, assumptions):
    res = run(case, scenarios, assumptions, make_plan(reservations={"B": {2036: 111}}))
    bad = failed(res, "CAPACITY_EXCEEDED")
    assert bad[0]["metric"] == "reserved_capacity_t" and bad[0]["excess"] == pytest.approx(1)


def test_isru_without_reservation_limited_by_capacity_only(case, scenarios, assumptions):
    p = full_plan(investments=[{"investment_id": "LUNAR_ISRU", "financing_years": [2036]}])
    p["decisions"]["supply_orders"].append({"source_id": "D", "year": 2039, "ordered_t": 120})
    res = run(case, scenarios, assumptions, p)
    d = year_row(res, "source_schedule", 2039, source_id="D")
    assert d["delivered_actual_t"] == pytest.approx(120) and d["reservation_payment_mln"] == 0
    assert not failed(res, "ORDER_EXCEEDS_RESERVATION")


def test_isru_financed_too_late(case, scenarios, assumptions):
    p = full_plan(investments=[{"investment_id": "LUNAR_ISRU", "financing_years": [2037, 2038]}])
    p["decisions"]["supply_orders"].append({"source_id": "D", "year": 2039, "ordered_t": 50})
    res = run(case, scenarios, assumptions, p)
    assert failed(res, "ISRU_FINANCING")[0]["year"] == 2038
    unavailable = failed(res, "SOURCE_UNAVAILABLE")
    assert unavailable[0]["source_id"] == "D" and unavailable[0]["excess"] == 50
    assert year_row(res, "source_schedule", 2039, source_id="D")["delivered_actual_t"] == 0
    assert year_row(res, "financial_breakdown", 2039)["fixed_opex_mln"] == 0
    assert res["totals"]["capex_total_mln"] == pytest.approx(1250)


def test_isru_financed_2037_available_2038(case, scenarios, assumptions):
    p = full_plan(investments=[{"investment_id": "LUNAR_ISRU", "financing_years": [2037]}])
    res = run(case, scenarios, assumptions, p)
    assert year_row(res, "source_schedule", 2038, source_id="D")["available_from"] == "2038-03"
    assert year_row(res, "financial_breakdown", 2037)["capex_mln"] == 1250


def test_order_without_investment_is_unavailable(case, scenarios, assumptions):
    res = run(case, scenarios, assumptions, make_plan(orders={"C": {2038: 10}, "D": {2038: 10}}))
    bad = failed(res, "SOURCE_UNAVAILABLE")
    assert {c["source_id"] for c in bad} == {"C", "D"}
    assert all("инвестиционного решения" in c["reason"] for c in bad)


def test_zbo_before_2036_not_available(case, scenarios, assumptions):
    res = run(case, scenarios, assumptions, full_plan(investments=[{"investment_id": "ZBO", "year": 2035}]))
    assert failed(res, "INVESTMENT_NOT_AVAILABLE")[0]["year"] == 2035
    assert all(r["storage_id"] == "BASE" for r in res["yearly_balance"])
    assert year_row(res, "financial_breakdown", 2035)["capex_mln"] == 180


def test_zbo_2036_switches_from_january(case, scenarios, assumptions):
    res = run(case, scenarios, assumptions, full_plan(investments=[{"investment_id": "ZBO", "year": 2036}]))
    assert year_row(res, "yearly_balance", 2035)["storage_id"] == "BASE"
    assert year_row(res, "yearly_balance", 2036)["storage_id"] == "ZBO"
    assert res["monthly_trace"][12]["capacity_t"] == 120
    assert year_row(res, "financial_breakdown", 2036)["fixed_opex_mln"] == 12


def test_earth_new_partial_year_prorates(case, scenarios, assumptions):
    a = with_assumptions(assumptions, earth_new_commissioning_months=18)
    p = full_plan(investments=[{"investment_id": "EARTH_NEW", "option_year": 2035, "exercise_year": 2036}])
    p["decisions"]["capacity_reservations"].append({"source_id": "C", "year": 2037, "reserved_capacity_t": 100})
    p["decisions"]["supply_orders"].append({"source_id": "C", "year": 2037, "ordered_t": 40})
    res = run(case, scenarios, a, p)
    c = year_row(res, "source_schedule", 2037, source_id="C")
    assert c["available_from"] == "2037-07" and c["available_months"] == 6
    assert c["capacity_available_t"] == pytest.approx(65)
    assert c["reservation_payment_mln"] == pytest.approx(0.3 * 100 * 0.5)
    assert c["payable_volume_t"] == pytest.approx(max(40, 0.5 * 100 * 0.5))
    months = [m for m in res["monthly_trace"] if m["year"] == 2037]
    assert sum(m["inflow_t"] for m in months[:6]) == pytest.approx(100 * 6 / 12)
    assert sum(m["inflow_t"] for m in months[6:]) == pytest.approx(100 * 6 / 12 + 40)


def test_earth_new_capex_is_90_plus_270(case, scenarios, assumptions):
    res = run(case, scenarios, assumptions, full_plan(investments=[{"investment_id": "EARTH_NEW", "option_year": 2036, "exercise_year": 2038}]))
    fin = {f["year"]: f["capex_mln"] for f in res["financial_breakdown"]}
    assert fin[2036] == 90 and fin[2038] == 270 and sum(fin.values()) == 360
    assert year_row(res, "source_schedule", 2040, source_id="C")["available_from"] == "2040-01"


def test_earth_new_commissioned_after_horizon_warns(case, scenarios, assumptions):
    res = run(case, scenarios, assumptions, full_plan(investments=[{"investment_id": "EARTH_NEW", "option_year": 2039, "exercise_year": 2040}]))
    assert any("за горизонт" in w for w in res["warnings"])
    assert res["totals"]["capex_total_mln"] == 360


def test_storage_overflow_reported(case, scenarios, assumptions):
    p = make_plan(orders={"A": {2035: 190}}, reservations={"A": {2035: 190}}, inventory={"initial_stock_t": 60})
    res = run(case, scenarios, assumptions, p)
    bad = failed(res, "STORAGE_CAPACITY")
    assert bad and bad[0]["year"] == 2035 and bad[0]["limit"] == 70 and bad[0]["excess"] > 0
    assert year_row(res, "yearly_balance", 2035)["overflow_t"] == pytest.approx(bad[0]["excess"])


def test_capex_limits(case, scenarios, assumptions):
    p = full_plan(investments=[{"investment_id": "EARTH_NEW", "option_year": 2035, "exercise_year": 2036},
                               {"investment_id": "LUNAR_ISRU", "financing_years": [2036]},
                               {"investment_id": "ZBO", "year": 2036}])
    res = run(case, scenarios, assumptions, p)
    assert not failed(res, "CAPEX_2037")
    assert year_row(res, "financial_breakdown", 2037)["cumulative_capex_mln"] == pytest.approx(1790)
    p2 = full_plan(investments=[{"investment_id": "EARTH_NEW", "option_year": 2035, "exercise_year": 2036},
                                {"investment_id": "LUNAR_ISRU", "financing_years": [2036]},
                                {"investment_id": "ZBO", "year": 2036}],
                   inventory_policy={"initial_stock_t": 0, "initial_stock_cost_mln": 0, "storage_id": "BASE"})
    res2 = run(case, scenarios, assumptions, p2)
    assert res2["totals"]["capex_total_mln"] == pytest.approx(1790)


def test_capex_2037_violation(case, scenarios, assumptions, tmp_path):
    from conftest import synthetic_case
    inv = [{"investment_id": "ZBO", "name": "ZBO", "option_fee_mln": 0, "exercise_cost_mln": 1900, "total_capex_mln": 1900,
            "commissioning_rule": "", "fixed_opex_mln_per_year": 0, "status": "SYNTHETIC", "notes": ""}]
    cons = [{"constraint_id": "CAPEX_2037", "metric": "cumulative_capex", "operator": "<=", "value": 1800, "unit": "mln",
             "period": "through_2037", "scenario": "ALL", "severity": "hard", "status": "SYNTHETIC", "description": ""},
            {"constraint_id": "CAPEX_2040", "metric": "cumulative_capex", "operator": "<=", "value": 2800, "unit": "mln",
             "period": "through_2040", "scenario": "ALL", "severity": "hard", "status": "SYNTHETIC", "description": ""}]
    demand = [{"year": y, "base_total_t": 10, "base_critical_t": 5, "low_total_t": 8, "high_total_t": 12, "status": "S"} for y in YEARS]
    case2 = synthetic_case(tmp_path, demand=demand, investments=inv, constraints=cons)
    sc = {"BASE": scenario_from_dict({"scenario_id": "BASE"}, case2)}
    res = run(case2, sc, assumptions, make_plan(investments=[{"investment_id": "ZBO", "year": 2037}]))
    bad = failed(res, "CAPEX_2037")
    assert bad and bad[0]["year"] == 2037 and bad[0]["excess"] == 100
    assert not failed(res, "CAPEX_2040")


def test_emergency_streak(case, scenarios, assumptions):
    orders = {"E": {2035: 60, 2036: 60, 2037: 60}, "A": {y: 30 for y in YEARS}}
    reservations = {"E": {2035: 80, 2036: 80, 2037: 80}, "A": {y: 40 for y in YEARS}}
    res = run(case, scenarios, assumptions, make_plan(orders=orders, reservations=reservations))
    bad = failed(res, "EMERGENCY_BASE_STREAK")
    assert bad and bad[0]["actual"] == 3 and bad[0]["year"] == 2037 and bad[0]["excess"] == 1
    assert [r["emergency_streak_years"] for r in res["yearly_balance"]] == [1, 2, 3, 0, 0, 0]
    orders["E"].pop(2037)
    reservations["E"].pop(2037)
    res2 = run(case, scenarios, assumptions, make_plan(orders=orders, reservations=reservations))
    assert not failed(res2, "EMERGENCY_BASE_STREAK")
    assert [r["emergency_base_channel"] for r in res2["yearly_balance"]] == [True, True, False, False, False, False]


def test_emergency_not_base_when_smaller(case, scenarios, assumptions):
    orders = {"E": {y: 20 for y in YEARS}, "A": {y: 100 for y in YEARS}}
    reservations = {"E": {y: 20 for y in YEARS}, "A": {y: 100 for y in YEARS}}
    res = run(case, scenarios, assumptions, make_plan(orders=orders, reservations=reservations))
    assert not failed(res, "EMERGENCY_BASE_STREAK")
    assert all(r["emergency_streak_years"] == 0 for r in res["yearly_balance"])


def test_reserve_exactly_45_days_passes(case, scenarios, assumptions):
    stock = 100 * 45 / 365
    res = run(case, scenarios, assumptions, make_plan(inventory={"initial_stock_t": stock}))
    row = [c for c in res["constraint_checks"] if c["rule_id"] == "RESERVE_45D" and c["year"] == 2035][0]
    assert row["ok"] and row["actual"] == pytest.approx(45)
    res2 = run(case, scenarios, assumptions, make_plan(inventory={"initial_stock_t": stock - 0.01}))
    row2 = [c for c in res2["constraint_checks"] if c["rule_id"] == "RESERVE_45D" and c["year"] == 2035][0]
    assert not row2["ok"] and row2["excess"] > 0


def test_emergency_reservation_counts_when_stock_covers_wait(case, scenarios, assumptions):
    stock = 100 * 42 / 365 + 0.5
    p = make_plan(reservations={"E": {2035: 10}}, inventory={"initial_stock_t": stock})
    res = run(case, scenarios, assumptions, p)
    row = [c for c in res["constraint_checks"] if c["rule_id"] == "RESERVE_45D" and c["year"] == 2035][0]
    assert row["ok"] and row["actual"] == 45 and "Emergency" in row["reason"]
    p2 = make_plan(reservations={"E": {2035: 10}}, inventory={"initial_stock_t": stock - 1})
    res2 = run(case, scenarios, assumptions, p2)
    row2 = [c for c in res2["constraint_checks"] if c["rule_id"] == "RESERVE_45D" and c["year"] == 2035][0]
    assert not row2["ok"] and "не засчитана" in row2["reason"]
    p3 = make_plan(reservations={"E": {2035: 0.1}}, inventory={"initial_stock_t": stock})
    res3 = run(case, scenarios, assumptions, p3)
    row3 = [c for c in res3["constraint_checks"] if c["rule_id"] == "RESERVE_45D" and c["year"] == 2035][0]
    assert not row3["ok"] and "больше брони" in row3["reason"]


def test_shortage_serves_critical_first(case, scenarios, assumptions):
    p = make_plan(orders={"A": {2035: 85}}, reservations={"A": {2035: 85}})
    res = run(case, scenarios, assumptions, p)
    r = year_row(res, "yearly_balance", 2035)
    assert r["delivered_actual_t"] == 85 and r["losses_t"] == pytest.approx(85 * 0.045)
    assert r["served_critical_t"] == pytest.approx(80)
    assert r["shortage_critical_t"] == 0
    assert r["served_total_t"] == pytest.approx(85 * 0.955)
    assert r["shortage_total_t"] == pytest.approx(100 - 85 * 0.955)
    assert r["closing_stock_t"] == 0
    assert res["feasible"] is False
    assert failed(res, "BASE_TOTAL_SERVICE")[0]["year"] == 2035


def test_critical_shortage_when_nothing_delivered(case, scenarios, assumptions):
    res = run(case, scenarios, assumptions, make_plan())
    r = year_row(res, "yearly_balance", 2035)
    assert r["served_total_t"] == 0 and r["shortage_critical_t"] == 80 and r["service_level_critical"] == 0
    assert failed(res, "BASE_CRITICAL_SERVICE")[0]["excess"] == pytest.approx(0.99)


def test_repeatable_and_json_clean(case, scenarios, assumptions, base_plan_dict):
    a = json.dumps(run(case, scenarios, assumptions, base_plan_dict), sort_keys=True)
    b = json.dumps(run(case, scenarios, assumptions, base_plan_dict), sort_keys=True)
    assert a == b
    assert "Infinity" not in a and "NaN" not in a
    json.loads(a)


def test_result_has_export_envelope_keys(base):
    required = {"scenario_id", "plan_id", "units", "assumptions_reference", "yearly_balance", "source_schedule",
                "inventory_trace", "financial_breakdown", "constraint_checks", "risk_register"}
    assert required <= set(base)
    assert base["meta"]["data_hash"] and base["meta"]["engine_version"]
    assert base["meta"]["plan"]["plan_id"] == "base-v1"
    assert any(a["name"] == "discount_rate" for a in base["meta"]["assumptions"])


def test_checks_sorted_failures_first(stress):
    oks = [c["ok"] for c in stress["constraint_checks"]]
    assert oks == sorted(oks)


def test_discount_rate_override_changes_pv_only(case, scenarios, assumptions, base_plan_dict):
    a = with_assumptions(assumptions, discount_rate=0.0)
    res = run(case, scenarios, a, base_plan_dict)
    assert res["totals"]["pv_total_mln"] == pytest.approx(res["totals"]["total_cost_mln"])
    assert all(f["discount_factor"] == 1 for f in res["financial_breakdown"])


def test_variable_payment_basis_plan(case, scenarios, assumptions, base_plan_dict):
    a = with_assumptions(assumptions, variable_payment_basis="plan")
    res = run(case, scenarios, a, base_plan_dict, "MANDATORY_STRESS")
    d = year_row(res, "source_schedule", 2038, source_id="D")
    assert d["payable_volume_t"] == pytest.approx(d["delivered_plan_t"])


def test_low_and_high_demand_scenarios(case, scenarios, assumptions, base_plan_dict):
    low = scenario_from_dict({"scenario_id": "TEAM_LOW", "demand_profile": "low"}, case)
    high = scenario_from_dict({"scenario_id": "TEAM_HIGH", "demand_profile": "high"}, case)
    sc = dict(scenarios, TEAM_LOW=low, TEAM_HIGH=high)
    rl = run(case, sc, assumptions, base_plan_dict, "TEAM_LOW")
    rh = run(case, sc, assumptions, base_plan_dict, "TEAM_HIGH")
    assert year_row(rl, "yearly_balance", 2040)["demand_total_t"] == 312
    assert year_row(rh, "yearly_balance", 2040)["demand_total_t"] == 487.5
    assert rl["totals"]["shortage_total_t"] == 0
    assert rh["totals"]["shortage_total_t"] > 0
    assert year_row(rh, "yearly_balance", 2038)["demand_critical_t"] == pytest.approx(312.5 * 170 / 250)


def test_constraint_profile_makes_base_rules_hard(case, scenarios, assumptions):
    plan = make_plan(orders={"A": {y: 100 for y in case.years}}, reservations={"A": {y: 100 for y in case.years}})
    low = run(case, scenarios, assumptions, plan, "TEAM_LOW_DEMAND")
    svc = [c for c in low["constraint_checks"] if c["rule_id"] == "BASE_TOTAL_SERVICE"]
    assert svc and all(c["severity"] == "hard" for c in svc)
    squeeze = run(case, scenarios, assumptions, plan, "TEAM_FLEX_SQUEEZE")
    assert all(c["severity"] == "info" for c in squeeze["constraint_checks"] if c["rule_id"].startswith("BASE_"))
    assert any(c["rule_id"] == "STRESS_LOSS_LIMIT" and c["severity"] == "hard" for c in squeeze["constraint_checks"])


def test_overrides_change_case_and_hash(case, scenarios, assumptions):
    from fuelhub.data import with_overrides
    over, errors = with_overrides(case, {"sources": {"A": {"price": 7.0}}, "storages": {"ZBO": {"capacity": 150}}, "demand": {"2040": {"total": 420, "critical": 260}}})
    assert errors == []
    assert over.sources["A"].price == 7.0 and case.sources["A"].price == 6.2
    assert over.storages["ZBO"].capacity == 150 and over.demand[2040].total == 420
    assert over.data_hash.startswith(case.data_hash + "+") and over.overrides["demand"]["2040"] == {"total": 420.0, "critical": 260.0}
    plan = parse_plan(full_plan(), over)
    res = calculate(over, scenarios["BASE"], plan, assumptions)
    assert res["meta"]["overrides"] == over.overrides and res["meta"]["data_hash"] == over.data_hash
    assert year_row(res, "yearly_balance", 2040)["demand_total_t"] == 420
    assert year_row(res, "source_schedule", 2035, source_id="A")["price_mln_per_t"] == 7.0
    same, errors = with_overrides(case, {"sources": {"A": {"price": 6.2}}})
    assert errors == [] and same is case


def test_overrides_are_validated(case):
    from fuelhub.data import with_overrides
    bad = {"sources": {"Z": {"price": 1}, "A": {"name": "x", "price": -1, "capacity": True}}, "demand": {"2041": {"total": 1}}, "foo": {}}
    over, errors = with_overrides(case, bad)
    assert over is case
    paths = [e["path"] for e in errors]
    assert paths == ["overrides.sources.Z", "overrides.sources.A.name", "overrides.sources.A.price", "overrides.sources.A.capacity", "overrides.demand.2041", "overrides.foo"]
