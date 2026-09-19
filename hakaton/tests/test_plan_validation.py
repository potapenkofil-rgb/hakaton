import json

import pytest

from fuelhub import PlanError, parse_plan
from fuelhub.plan import load_plan, save_plan
from fuelhub.scenario import scenario_from_dict

from conftest import REF, failed, make_plan, run, synthetic_case, year_row


def errors(exc: PlanError) -> dict:
    return {d["path"]: d["message"] for d in exc.details}


def test_base_plan_parses(case, scenarios, base_plan_dict):
    plan = parse_plan(base_plan_dict, case, scenarios)
    assert plan.plan_id == "base-v1"
    assert plan.ordered("A", 2035) == 95
    assert plan.reserved("C", 2038) == 130
    assert plan.investment("EARTH_NEW").exercise_year == 2036
    assert plan.investment("LUNAR_ISRU").financing_years == (2036, 2037)
    assert plan.to_dict()["decisions"]["inventory_policy"]["initial_stock_t"] == 15


def test_empty_plan_is_valid(case, scenarios):
    raw = json.loads((REF / "empty_plan.json").read_text(encoding="utf-8"))
    plan = parse_plan(raw, case, scenarios)
    assert plan.orders == () and plan.investments == ()


def test_organizer_negative_reservation_rejected(case, scenarios):
    raw = json.loads((REF / "invalid_plan_examples" / "negative_reservation.json").read_text(encoding="utf-8"))
    with pytest.raises(PlanError) as e:
        parse_plan(raw, case, scenarios)
    paths = errors(e.value)
    assert "decisions.capacity_reservations[0].source_id" in paths
    assert e.value.to_dict()["error"] == "INVALID_PLAN"


def test_negative_reservation_message(case, scenarios):
    raw = make_plan(reservations={"A": {2035: -1}})
    with pytest.raises(PlanError) as e:
        parse_plan(raw, case, scenarios)
    assert errors(e.value) == {"decisions.capacity_reservations[0].reserved_capacity_t": "отрицательный объём: -1"}


def test_organizer_over_capacity_is_violation_not_input_error(tmp_path, assumptions):
    case = synthetic_case(tmp_path)
    raw = json.loads((REF / "invalid_plan_examples" / "over_capacity.json").read_text(encoding="utf-8"))
    raw["decisions"]["capacity_reservations"][0]["source_id"] = "X"
    sc = {"SYNTHETIC": scenario_from_dict({"scenario_id": "SYNTHETIC"}, case)}
    res = run(case, sc, assumptions, raw, "SYNTHETIC")
    bad = failed(res, "CAPACITY_EXCEEDED")
    assert bad and bad[0]["excess"] == 2 and bad[0]["actual"] == 12 and bad[0]["limit"] == 10


def test_organizer_malformed_scenario_rejected(case):
    raw = json.loads((REF / "invalid_plan_examples" / "malformed_scenario.json").read_text(encoding="utf-8"))
    with pytest.raises(ValueError):
        scenario_from_dict(raw, case)


@pytest.mark.parametrize("raw,path", [
    ({}, "plan_id"),
    ({"plan_id": "x"}, "scenario_id"),
    ({"plan_id": "x", "scenario_id": "BASE"}, "decisions"),
    ({"plan_id": "x", "scenario_id": "BASE", "decisions": {}}, "decisions.supply_orders"),
    ({"plan_id": "x", "scenario_id": "", "decisions": {"supply_orders": [], "capacity_reservations": [], "investments": [], "inventory_policy": {}}}, "scenario_id"),
    ([], ""),
])
def test_shape_errors(case, scenarios, raw, path):
    with pytest.raises(PlanError) as e:
        parse_plan(raw, case, scenarios)
    assert path in errors(e.value)


@pytest.mark.parametrize("orders,path,fragment", [
    ({"F": {2035: 1}}, "decisions.supply_orders[0].source_id", "неизвестный канал F"),
    ({"A": {2041: 1}}, "decisions.supply_orders[0].year", "вне горизонта"),
    ({"A": {2034: 1}}, "decisions.supply_orders[0].year", "вне горизонта"),
    ({"A": {2035: "10"}}, "decisions.supply_orders[0].ordered_t", "ожидалось число"),
    ({"A": {2035: -3}}, "decisions.supply_orders[0].ordered_t", "отрицательный"),
])
def test_order_errors(case, scenarios, orders, path, fragment):
    with pytest.raises(PlanError) as e:
        parse_plan(make_plan(orders=orders), case, scenarios)
    assert fragment in errors(e.value)[path]


def test_year_as_string_rejected(case, scenarios):
    raw = make_plan()
    raw["decisions"]["supply_orders"].append({"source_id": "A", "year": "2035", "ordered_t": 1})
    with pytest.raises(PlanError) as e:
        parse_plan(raw, case, scenarios)
    assert "ожидался год" in errors(e.value)["decisions.supply_orders[0].year"]


def test_duplicate_order_rejected(case, scenarios):
    raw = make_plan()
    raw["decisions"]["supply_orders"] = [{"source_id": "A", "year": 2035, "ordered_t": 1}, {"source_id": "A", "year": 2035, "ordered_t": 2}]
    with pytest.raises(PlanError) as e:
        parse_plan(raw, case, scenarios)
    assert "дважды" in errors(e.value)["decisions.supply_orders[1]"]


def test_bool_is_not_a_number(case, scenarios):
    with pytest.raises(PlanError):
        parse_plan(make_plan(orders={"A": {2035: True}}), case, scenarios)


@pytest.mark.parametrize("inv,path", [
    ({"investment_id": "MARS"}, "decisions.investments[0].investment_id"),
    ({"investment_id": "EARTH_NEW", "option_year": 2036, "exercise_year": 2035}, "decisions.investments[0].exercise_year"),
    ({"investment_id": "EARTH_NEW", "option_year": 2035}, "decisions.investments[0].exercise_year"),
    ({"investment_id": "LUNAR_ISRU"}, "decisions.investments[0].financing_years"),
    ({"investment_id": "LUNAR_ISRU", "financing_years": []}, "decisions.investments[0].financing_years"),
    ({"investment_id": "LUNAR_ISRU", "financing_years": [2041]}, "decisions.investments[0].financing_years[0]"),
    ({"investment_id": "ZBO"}, "decisions.investments[0].year"),
])
def test_investment_errors(case, scenarios, inv, path):
    with pytest.raises(PlanError) as e:
        parse_plan(make_plan(investments=[inv]), case, scenarios)
    assert path in errors(e.value)


def test_duplicate_investment_rejected(case, scenarios):
    with pytest.raises(PlanError) as e:
        parse_plan(make_plan(investments=[{"investment_id": "ZBO", "year": 2036}, {"investment_id": "ZBO", "year": 2037}]), case, scenarios)
    assert "дважды" in errors(e.value)["decisions.investments[1]"]


def test_isru_year_shorthand(case, scenarios):
    plan = parse_plan(make_plan(investments=[{"investment_id": "LUNAR_ISRU", "year": 2037}]), case, scenarios)
    assert plan.investment("LUNAR_ISRU").financing_years == (2037,)


@pytest.mark.parametrize("inventory,path", [
    ({"initial_stock_t": -1}, "decisions.inventory_policy.initial_stock_t"),
    ({"initial_stock_source_id": "Q"}, "decisions.inventory_policy.initial_stock_source_id"),
    ({"storage_id": "TANK"}, "decisions.inventory_policy.storage_id"),
])
def test_inventory_errors(case, scenarios, inventory, path):
    with pytest.raises(PlanError) as e:
        parse_plan(make_plan(inventory=inventory), case, scenarios)
    assert path in errors(e.value)


def test_multiple_errors_reported_together(case, scenarios):
    raw = make_plan(orders={"F": {2035: -1}}, reservations={"A": {2050: 1}})
    with pytest.raises(PlanError) as e:
        parse_plan(raw, case, scenarios)
    assert len(e.value.details) == 3


def test_extra_fields_ignored(case, scenarios, base_plan_dict):
    raw = json.loads(json.dumps(base_plan_dict))
    raw["comment"] = "лишнее поле"
    raw["decisions"]["supply_orders"][0]["note"] = "тоже лишнее"
    plan = parse_plan(raw, case, scenarios)
    assert plan.ordered("A", 2035) == 95


def test_save_and_load_roundtrip(case, scenarios, base_plan_dict, tmp_path):
    plan = parse_plan(base_plan_dict, case, scenarios)
    p = save_plan(plan, tmp_path / "plans" / "p.json")
    again = load_plan(p, case, scenarios)
    assert again == plan
    assert again.to_dict() == plan.to_dict()


def test_load_plan_bad_json(case, scenarios, tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{not json", encoding="utf-8")
    with pytest.raises(PlanError) as e:
        load_plan(p, case, scenarios)
    assert "JSON" in e.value.details[0]["message"]
