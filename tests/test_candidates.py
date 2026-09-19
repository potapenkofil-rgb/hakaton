import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import check_response
from fuelhub.cli import Context
from fuelhub.plan import parse_plan

PAIRS = [("v3-earth", 55), ("v3-full", 55), ("v3-lunar", 55), ("v2-earth", 45)]


@pytest.fixture(scope="module")
def ctx():
    return Context()


def load(name):
    return json.load(open(ROOT / "results" / "plans" / f"{name}.json", encoding="utf-8"))


def run(ctx, name, scenario):
    return ctx.run(parse_plan(load(name), ctx.case), scenario)


def hard(r):
    return [c["rule_id"] for c in r["constraint_checks"] if not c["ok"] and c["severity"] == "hard"]


@pytest.mark.parametrize("name,margin", PAIRS)
def test_base_plan_feasible_in_base(ctx, name, margin):
    r = run(ctx, name, "BASE")
    assert r["feasible"], hard(r)
    assert r["totals"]["shortage_total_t"] == 0
    assert r["yearly_balance"][0]["reserve_equivalent_days"] >= 45
    assert min(y["reserve_equivalent_days"] for y in r["yearly_balance"] if y["year"] > 2035) >= margin - 1e-6


@pytest.mark.parametrize("name,margin", PAIRS)
def test_response_feasible_in_stress(ctx, name, margin):
    r = run(ctx, f"{name}-response", "MANDATORY_STRESS")
    assert r["feasible"], hard(r)
    assert r["totals"]["shortage_total_t"] == 0


@pytest.mark.parametrize("name,margin", PAIRS)
def test_response_obeys_reaction_rule(ctx, name, margin):
    changes, problems, order_by = check_response.check(load(name), load(f"{name}-response"), ctx)
    assert changes
    assert problems == []
    for (kind, src, year), _, _ in changes:
        assert src in ("B", "E") and year >= 2039
        if kind == "заказ":
            assert order_by[(src, year)] >= "2038-01"


def test_base_alone_fails_stress_and_response_alone_fails_base(ctx):
    assert "RESERVE_45D" in hard(run(ctx, "v3-earth", "MANDATORY_STRESS"))
    assert "STORAGE_CAPACITY" in hard(run(ctx, "v3-earth-response", "BASE"))


def test_recommended_plan_cheaper_than_hand_made(ctx):
    ours = run(ctx, "v3-earth", "BASE")["totals"]["pv_total_mln"]
    hand = run(ctx, "base-v1", "BASE")["totals"]["pv_total_mln"]
    assert ours < hand
    assert run(ctx, "v3-earth", "BASE")["totals"]["capex_total_mln"] == 540


def test_margin_costs_little(ctx):
    thin = run(ctx, "v2-earth", "BASE")["totals"]["pv_total_mln"]
    safe = run(ctx, "v3-earth", "BASE")["totals"]["pv_total_mln"]
    assert 0 <= safe - thin < 100


def test_generated_plans_have_no_isru_reservations():
    for f in (ROOT / "results" / "plans").glob("v[23]-*.json"):
        raw = json.load(open(f, encoding="utf-8"))
        assert all(r["source_id"] != "D" for r in raw["decisions"]["capacity_reservations"]), f.name
