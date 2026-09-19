import csv
import shutil

import pytest

from fuelhub import DATA_DIR, ROOT, load_case, load_scenarios, parse_yaml, scenario_from_dict
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


def test_repo_copy_horizon_2041():
    ctx = Context(ROOT / "data_ext" / "horizon_2041")
    assert ctx.case.years[-1] == 2041 and "X" in ctx.case.sources
    assert ctx.case.data_hash != load_case().data_hash
    rows = list(csv.DictReader((ROOT / "data_ext" / "horizon_2041" / "supply_sources.csv").open(encoding="utf-8")))
    assert [r["status"] for r in rows if r["source_id"] == "X"] == ["TEAM_ASSUMPTION"]
    res = ctx.run(ctx.plan(ROOT / "results" / "plans" / "v3-earth.json"), "BASE")
    assert len(res["yearly_balance"]) == 7
    assert year_row(res, "yearly_balance", 2041)["demand_total_t"] == 450
    assert any(c["rule_id"] == "RESERVE_45D" and c["year"] == 2041 for c in res["constraint_checks"])
    assert any(c["rule_id"] == "CAPEX_2040" for c in res["constraint_checks"])


def test_repo_copy_loss_2pct():
    ctx = Context(ROOT / "data_ext" / "loss_2pct")
    assert ctx.case.storages["ZBO"].loss_rate == pytest.approx(0.02)
    plan = ROOT / "results" / "plans" / "v3-earth-response.json"
    loose = ctx.run(ctx.plan(plan), "MANDATORY_STRESS")
    tight = Context().run(Context().plan(plan), "MANDATORY_STRESS")
    assert loose["totals"]["losses_t"] > tight["totals"]["losses_t"]
    limits = [c for c in loose["constraint_checks"] if c["rule_id"] == "STRESS_LOSS_LIMIT"]
    assert limits and all(c["ok"] for c in limits)


def test_continuation_plan_for_2041():
    ctx = Context(ROOT / "data_ext" / "horizon_2041")
    plan = ctx.plan(ROOT / "results" / "plans" / "v3-earth-2041.json")
    base = Context().plan(ROOT / "results" / "plans" / "v3-earth.json")
    assert [i.to_dict() for i in plan.investments] == [i.to_dict() for i in base.investments]
    for o in base.orders:
        if not (o.source_id == "B" and o.year == 2040):
            assert plan.ordered(o.source_id, o.year) == o.ordered_t
    res = ctx.run(plan, "TEAM_HORIZON_2041")
    assert res["feasible"] and res["totals"]["shortage_total_t"] == 0
    assert year_row(res, "source_schedule", 2041, source_id="X")["delivered_actual_t"] == 60
    assert res["meta"]["scenario"]["constraint_profile"] == "BASE"
    old = ctx.run(base, "TEAM_HORIZON_2041")
    assert not old["feasible"] and year_row(old, "yearly_balance", 2041)["shortage_total_t"] > 400
