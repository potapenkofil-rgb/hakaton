import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import check_response
import compare_plans
import optimize
import sensitivity
from fuelhub.cli import Context
from fuelhub.scenario import SCENARIO_DIR, parse_yaml


@pytest.fixture(scope="module")
def ctx():
    return Context()


def load(name):
    return json.load(open(ROOT / "results" / "plans" / f"{name}.json", encoding="utf-8"))


def test_old_response_breaks_reaction_rule(ctx):
    changes, problems, order_by = check_response.check(load("base-v1"), load("stress-response"), ctx)
    assert changes
    assert any("2038" in p for p in problems)
    assert order_by[("B", 2039)] == "2038-09"


def test_response_equal_to_base_passes(ctx):
    base = load("base-v1")
    changes, problems, _ = check_response.check(base, base, ctx)
    assert changes == [] and problems == []


def test_sensitivity_variant_touches_only_shock_years():
    raw = parse_yaml((SCENARIO_DIR / "base.yaml").read_text(encoding="utf-8"))
    v = sensitivity.variant(raw, "demand", 1.1)
    assert v["demand_multiplier"]["2039"] == pytest.approx(1.1)
    assert v["demand_multiplier"].get("2035", v["demand_multiplier"].get("default")) == pytest.approx(1.0)
    v2 = sensitivity.variant(raw, "isru", 0.5)
    assert v2["actual_delivery_share"]["Lunar-ISRU"]["2038"] == pytest.approx(0.5)
    assert v["status"] == "TEAM_ASSUMPTION"


def test_sensitivity_run_matches_engine(ctx):
    from fuelhub.plan import parse_plan
    raw = parse_yaml((SCENARIO_DIR / "base.yaml").read_text(encoding="utf-8"))
    plan = parse_plan(load("base-v1"), ctx.case)
    res = sensitivity.run(ctx, plan, sensitivity.variant(raw, "price", 1.0))
    assert res["feasible"] is True
    assert res["pv_total_mln"] == pytest.approx(ctx.run(plan, "BASE")["totals"]["pv_total_mln"], abs=0.1)


def test_compare_row(ctx):
    r = compare_plans.row(ctx, load("base-v1"), "MANDATORY_STRESS")
    assert r["feasible"] is False
    assert "RESERVE_45D 2039" in r["violations"]
    assert set(compare_plans.COLUMNS) == set(r)


def test_optimizer_plan_roundtrip(ctx):
    template = load("base-v1")
    s = optimize.Search(ctx, template, "full", 1)
    rebuilt = s.plan(s.base, "x", "BASE")
    assert optimize.Search.cells_from(rebuilt) == {k: v for k, v in s.base.items() if v > 0}
    assert rebuilt["decisions"]["investments"] == template["decisions"]["investments"]


def test_optimizer_short_run_is_deterministic(ctx):
    template = load("base-v1")
    a = optimize.Search(ctx, template, "earth", 7)
    b = optimize.Search(ctx, template, "earth", 7)
    sa, _, _ = a.optimize(40, False)
    sb, _, _ = b.optimize(40, False)
    assert sa == pytest.approx(sb)
    assert a.base == b.base and a.resp == b.resp
    for (kind, src, year) in a.resp:
        assert src in optimize.RESPONSE_SOURCES and year >= optimize.RESPONSE_FROM
