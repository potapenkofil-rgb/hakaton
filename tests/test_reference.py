import pytest

from fuelhub import rules
from fuelhub.scenario import scenario_from_dict

from conftest import failed, make_plan, run, synthetic_case, year_row


def test_v01_material_balance(expected_checks):
    assert rules.closing_inventory(10, 30, 2, 25) == expected_checks["V01"]["closing_inventory_t"]


def test_v02_shortage_is_not_negative_inventory(expected_checks):
    served_c, served_k, shortage = rules.serve(0 + 8 - 0, 10, 0)
    exp = expected_checks["V02"]
    assert served_c + served_k == exp["served_t"]
    assert shortage == exp["shortage_t"]
    assert rules.closing_inventory(0, 8, 0, served_c + served_k) == exp["closing_inventory_t"]


def test_v03_take_or_pay_minimum(expected_checks):
    payable = rules.payable_volume(50, 100, 0.70)
    exp = expected_checks["V03"]
    assert payable == exp["payable_volume_t"]
    assert rules.variable_payment(2, payable) == exp["variable_payment_mln"]


def test_v04_take_or_pay_not_charged_twice(expected_checks, tmp_path, assumptions, scenarios):
    case = synthetic_case(tmp_path, sources=[{
        "source_id": "X", "name": "Source-X", "capacity_t_per_year": 100, "variable_cost_mln_per_t": 2,
        "reservation_rate_mln_per_t_year_capacity": 0, "take_or_pay_share": 0.7, "lead_time_min_value": 1,
        "lead_time_max_value": 1, "lead_time_unit": "month", "reliability_profile": "constant:0.8",
        "available_from_year": 2035, "status": "SYNTHETIC", "notes": ""}])
    sc = {"BASE": scenario_from_dict({"scenario_id": "BASE"}, case)}
    res = run(case, sc, assumptions, make_plan(orders={"X": {2035: 50}}, reservations={"X": {2035: 100}}))
    row = year_row(res, "source_schedule", 2035, source_id="X")
    fin = year_row(res, "financial_breakdown", 2035)
    assert row["variable_payment_mln"] == expected_checks["V04"]["variable_payment_mln"]
    assert fin["procurement_mln"] == expected_checks["V04"]["variable_payment_mln"]
    assert fin["take_or_pay_topup_mln"] == pytest.approx(20 * 2)
    assert fin["total_mln"] == pytest.approx(fin["procurement_mln"] + fin["reservation_mln"] + fin["holding_mln"]
                                             + fin["fixed_opex_mln"] + fin["capex_mln"] + fin["initial_stock_mln"])


def test_v05_reservation_payment_prorated(expected_checks):
    assert rules.reservation_payment(0.4, 100, 0.5) == expected_checks["V05"]["reservation_payment_mln"]


def test_v06_losses_once_on_throughput(expected_checks):
    assert rules.losses_on_throughput(20, 0.05) == expected_checks["V06"]["losses_t"]


def test_v07_45_day_reserve(expected_checks):
    assert rules.reserve_requirement(365) == expected_checks["V07"]["reserve_t"]


def test_v08_capacity_exceeded(expected_checks, tmp_path, assumptions):
    case = synthetic_case(tmp_path)
    sc = {"BASE": scenario_from_dict({"scenario_id": "BASE"}, case)}
    res = run(case, sc, assumptions, make_plan(reservations={"X": {2035: 12}}))
    bad = failed(res, expected_checks["V08"]["violation"])
    assert bad, res["constraint_checks"]
    assert bad[0]["excess"] == expected_checks["V08"]["excess_t"]
    assert bad[0]["year"] == 2035 and bad[0]["source_id"] == "X"
    assert res["feasible"] is False


def test_v09_critical_demand_is_nested(expected_checks, tmp_path, assumptions):
    case = synthetic_case(tmp_path)
    sc = {"BASE": scenario_from_dict({"scenario_id": "BASE"}, case)}
    res = run(case, sc, assumptions, make_plan())
    row = year_row(res, "yearly_balance", 2035)
    assert row["demand_total_t"] == expected_checks["V09"]["total_demand_t"]
    assert row["demand_critical_t"] == 60
    assert res["totals"]["demand_total_t"] == 100


def test_v10_stress_delivery_not_multiplied_by_reliability(expected_checks, tmp_path, assumptions):
    case = synthetic_case(tmp_path, sources=[{
        "source_id": "X", "name": "Source-X", "capacity_t_per_year": 100, "variable_cost_mln_per_t": 2,
        "reservation_rate_mln_per_t_year_capacity": 0, "take_or_pay_share": 0, "lead_time_min_value": 1,
        "lead_time_max_value": 1, "lead_time_unit": "month", "reliability_profile": "constant:0.80",
        "available_from_year": 2035, "status": "SYNTHETIC", "notes": ""}])
    sc = {"S": scenario_from_dict({"scenario_id": "S", "actual_delivery_share": {"Source-X": {2035: 0.5}}}, case)}
    res = run(case, sc, assumptions, make_plan(orders={"X": {2035: 20}}), "S")
    row = year_row(res, "source_schedule", 2035, source_id="X")
    assert row["delivered_plan_t"] == 20
    assert row["delivered_actual_t"] == expected_checks["V10"]["actual_delivery_t"]
    assert row["reliability"] == 0.8
    assert rules.actual_delivery(20, 0.5) == 10
