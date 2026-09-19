import csv
import shutil

import pytest

from fuelhub import DATA_DIR, load_case, load_scenarios, parse_yaml, scenario_from_dict
from fuelhub.cli import Context

from conftest import failed, make_plan, run, year_row


def extend_data(tmp_path):
    d = tmp_path / "data_ext"
    shutil.copytree(DATA_DIR, d)
    with (d / "demand.csv").open("a", encoding="utf-8", newline="") as f:
        csv.writer(f).writerow([2041, 450, 290, 360, 562.5, "TEAM_ASSUMPTION"])
    with (d / "supply_sources.csv").open("a", encoding="utf-8", newline="") as f:
        csv.writer(f).writerow(["X", "Source-X", 60, 5.0, 0.2, 0.3, 6, 6, "month", "constant:0.9", 2040, "TEAM_ASSUMPTION", "исследовательский канал"])
    return d


def test_extended_horizon_and_source(tmp_path, assumptions):
    d = extend_data(tmp_path)
    case = load_case(d)
    assert case.years == (2035, 2036, 2037, 2038, 2039, 2040, 2041)
    assert "X" in case.sources and case.sources["X"].available_from == 2040
    assert case.data_hash != load_case().data_hash
    sc = load_scenarios(case)
    team = scenario_from_dict(parse_yaml("""
scenario_id: TEAM_HORIZON_2041
label_ru: "Горизонт 2041 с Source-X"
status: TEAM_ASSUMPTION
demand_multiplier:
  2041: 1.0
variable_price_multiplier:
  Source-X:
    2041: 1.1
"""), case)
    sc[team.id] = team
    orders = {"A": {y: 150 for y in case.years}, "B": {y: 60 for y in case.years}, "X": {2040: 30, 2041: 60}}
    reservations = {"A": {y: 190 for y in case.years}, "B": {y: 110 for y in case.years}, "X": {2040: 60, 2041: 60}}
    plan = make_plan(orders=orders, reservations=reservations, inventory={"initial_stock_t": 30})
    res = run(case, sc, assumptions, plan, "TEAM_HORIZON_2041")
    assert len(res["yearly_balance"]) == 7 and len(res["monthly_trace"]) == 84
    x41 = year_row(res, "source_schedule", 2041, source_id="X")
    assert x41["delivered_actual_t"] == 60 and x41["price_mln_per_t"] == pytest.approx(5.5)
    assert year_row(res, "source_schedule", 2039, source_id="X")["available"] is False
    assert failed(res, "SOURCE_UNAVAILABLE") == []
    caps = [c for c in res["constraint_checks"] if c["rule_id"] == "CAPEX_2040"]
    assert caps and caps[0]["year"] == 2040
    assert any(c["rule_id"] == "RESERVE_45D" and c["year"] == 2041 for c in res["constraint_checks"])


def test_context_with_custom_dirs(tmp_path):
    d = extend_data(tmp_path)
    sdir = tmp_path / "scenarios"
    sdir.mkdir()
    shutil.copy(DATA_DIR.parent / "configs" / "scenarios" / "base.yaml", sdir / "base.yaml")
    (sdir / "team_x.yaml").write_text("scenario_id: TEAM_X\ndemand_profile: high\n", encoding="utf-8")
    ctx = Context(d, sdir)
    assert set(ctx.scenarios) == {"BASE", "TEAM_X"}
    plan = ctx.plan(DATA_DIR.parent / "results" / "plans" / "base-v1.json")
    res = ctx.run(plan, "TEAM_X")
    assert year_row(res, "yearly_balance", 2041)["demand_total_t"] == 562.5


def test_organizer_limits_still_apply_in_extension(tmp_path, assumptions):
    d = extend_data(tmp_path)
    case = load_case(d)
    sc = load_scenarios(case)
    plan = make_plan(orders={"X": {2041: 61}}, reservations={"X": {2041: 61}})
    res = run(case, sc, assumptions, plan)
    assert failed(res, "CAPACITY_EXCEEDED")[0]["excess"] == 1
    assert {c["rule_id"] for c in res["constraint_checks"]} >= {"CAPEX_2037", "CAPEX_2040", "RESERVE_45D"}
