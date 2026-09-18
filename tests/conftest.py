import csv
import json
from pathlib import Path

import pytest

from fuelhub import ROOT, calculate, load_assumptions, load_case, load_scenarios, parse_plan
from fuelhub.data import Assumption, Assumptions

REF = Path(__file__).parent / "reference"
YEARS = (2035, 2036, 2037, 2038, 2039, 2040)


@pytest.fixture(scope="session")
def case():
    return load_case()


@pytest.fixture(scope="session")
def assumptions():
    return load_assumptions()


@pytest.fixture(scope="session")
def scenarios(case):
    return load_scenarios(case)


@pytest.fixture(scope="session")
def expected_checks():
    return {c["case_id"]: c["expected"] for c in json.loads((REF / "expected_checks.json").read_text(encoding="utf-8"))}


@pytest.fixture(scope="session")
def base_plan_dict():
    return json.loads((ROOT / "results" / "plans" / "base-v1.json").read_text(encoding="utf-8"))


def make_plan(orders=None, reservations=None, investments=None, inventory=None, plan_id="t", scenario_id="BASE"):
    def rows(spec, key):
        out = []
        for sid, years in (spec or {}).items():
            for y, q in years.items():
                out.append({"source_id": sid, "year": y, key: q})
        return out

    inv = {"initial_stock_t": 0, "initial_stock_cost_mln": 0, "storage_id": "BASE"}
    inv.update(inventory or {})
    return {
        "plan_id": plan_id,
        "scenario_id": scenario_id,
        "decisions": {
            "supply_orders": rows(orders, "ordered_t"),
            "capacity_reservations": rows(reservations, "reserved_capacity_t"),
            "investments": list(investments or []),
            "inventory_policy": inv,
        },
    }


def with_assumptions(base: Assumptions, **overrides) -> Assumptions:
    items = [Assumption(a.name, overrides.pop(a.name, a.value), a.unit, a.source, a.scope) for a in base.items]
    for k, v in overrides.items():
        items.append(Assumption(k, v, "", "test", "test"))
    return Assumptions(items, base.path)


def run(case, scenarios, assumptions, plan_dict, scenario_id="BASE"):
    plan = parse_plan(plan_dict, case, scenarios)
    return calculate(case, scenarios[scenario_id], plan, assumptions)


def year_row(result, table, year, **match):
    for r in result[table]:
        if r["year"] == year and all(r.get(k) == v for k, v in match.items()):
            return r
    raise KeyError((table, year, match))


def failed(result, rule_id=None):
    return [c for c in result["constraint_checks"] if not c["ok"] and (rule_id is None or c["rule_id"] == rule_id)]


SOURCE_COLS = ["source_id", "name", "capacity_t_per_year", "variable_cost_mln_per_t", "reservation_rate_mln_per_t_year_capacity",
               "take_or_pay_share", "lead_time_min_value", "lead_time_max_value", "lead_time_unit", "reliability_profile",
               "available_from_year", "status", "notes"]
STORAGE_COLS = ["storage_id", "name", "capacity_t", "loss_rate_on_throughput", "holding_cost_mln_per_t_year", "capex_mln",
                "fixed_opex_mln_per_year", "available_from_year", "status", "notes"]
INVEST_COLS = ["investment_id", "name", "option_fee_mln", "exercise_cost_mln", "total_capex_mln", "commissioning_rule",
               "fixed_opex_mln_per_year", "status", "notes"]
CONSTRAINT_COLS = ["constraint_id", "metric", "operator", "value", "unit", "period", "scenario", "severity", "status", "description"]
DEMAND_COLS = ["year", "base_total_t", "base_critical_t", "low_total_t", "high_total_t", "status"]


def write_csv(path: Path, cols, rows):
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for r in rows:
            w.writerow([r.get(c, "") for c in cols])


def synthetic_case(tmp_path: Path, sources=None, demand=None, storages=None, investments=None, constraints=None):
    d = tmp_path / "data"
    d.mkdir(exist_ok=True)
    if demand is None:
        demand = [{"year": 2035, "base_total_t": 100, "base_critical_t": 60, "low_total_t": 80, "high_total_t": 110, "status": "SYNTHETIC"}]
    if sources is None:
        sources = [{"source_id": "X", "name": "Source-X", "capacity_t_per_year": 10, "variable_cost_mln_per_t": 2,
                    "reservation_rate_mln_per_t_year_capacity": 0.4, "take_or_pay_share": 0.7, "lead_time_min_value": 1,
                    "lead_time_max_value": 1, "lead_time_unit": "month", "reliability_profile": "constant:0.8",
                    "available_from_year": 2035, "status": "SYNTHETIC", "notes": ""}]
    if storages is None:
        storages = [{"storage_id": "BASE", "name": "Base", "capacity_t": 1000, "loss_rate_on_throughput": 0.05,
                     "holding_cost_mln_per_t_year": 0, "capex_mln": 0, "fixed_opex_mln_per_year": 0, "available_from_year": 2035,
                     "status": "SYNTHETIC", "notes": ""},
                    {"storage_id": "ZBO", "name": "ZBO", "capacity_t": 2000, "loss_rate_on_throughput": 0.01,
                     "holding_cost_mln_per_t_year": 0, "capex_mln": 10, "fixed_opex_mln_per_year": 1, "available_from_year": 2036,
                     "status": "SYNTHETIC", "notes": ""}]
    if investments is None:
        investments = [{"investment_id": "ZBO", "name": "ZBO", "option_fee_mln": 0, "exercise_cost_mln": 10, "total_capex_mln": 10,
                        "commissioning_rule": "", "fixed_opex_mln_per_year": 1, "status": "SYNTHETIC", "notes": ""}]
    if constraints is None:
        constraints = [{"constraint_id": "BASE_TOTAL_SERVICE", "metric": "total_service_level", "operator": ">=", "value": 0.97,
                        "unit": "share", "period": "annual", "scenario": "BASE", "severity": "hard", "status": "SYNTHETIC", "description": ""}]
    write_csv(d / "demand.csv", DEMAND_COLS, demand)
    write_csv(d / "supply_sources.csv", SOURCE_COLS, sources)
    write_csv(d / "storage_options.csv", STORAGE_COLS, storages)
    write_csv(d / "investment_options.csv", INVEST_COLS, investments)
    write_csv(d / "constraints.csv", CONSTRAINT_COLS, constraints)
    return load_case(d)
