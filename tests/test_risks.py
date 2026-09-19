import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import risks
from fuelhub.cli import Context
from fuelhub.plan import parse_plan

REGISTER = json.load(open(ROOT / "configs" / "risks.json", encoding="utf-8"))
RISKS = {r["id"]: r for r in REGISTER["risks"]}
EXPECTED = {
    "R1": (False, True), "R2": (False, True), "R3": (False, True), "R4": (True, True),
    "R5": (True, True), "R6": (True, True), "R7": (False, True), "R8": (False, True),
}


@pytest.fixture(scope="module")
def contexts():
    return {}


@pytest.fixture(scope="module")
def assessed(contexts):
    return {r["id"]: risks.assess(REGISTER, r, contexts) for r in REGISTER["risks"]}


def test_register_is_complete():
    assert len(RISKS) >= 8 and REGISTER["status"] == "TEAM_ASSUMPTION"
    for r in RISKS.values():
        for key in ("title", "event", "cause", "period", "parameters", "dependencies", "owner", "likelihood", "scenario_id", "measure"):
            assert r.get(key), (r["id"], key)
        assert "title" in r["measure"] and "note" in r["measure"]


def test_register_loads_into_result(contexts):
    ctx = contexts.setdefault("", Context())
    res = ctx.run(ctx.plan(ROOT / "results" / "plans" / "v3-earth.json"), "BASE")
    assert [r["id"] for r in res["risk_register"]] == list(RISKS)


@pytest.mark.parametrize("rid", sorted(EXPECTED))
def test_hit_and_residual_as_documented(assessed, rid):
    hit, after = EXPECTED[rid]
    a = assessed[rid]
    assert a["hit"]["feasible"] is hit, a["hit"]
    assert a["after"]["feasible"] is after, a["after"]


@pytest.mark.parametrize("rid", [r for r in RISKS if RISKS[r]["measure"].get("prep")])
def test_preparation_keeps_base_feasible(assessed, rid):
    a = assessed[rid]
    assert a["prepared_feasible"]
    assert 0 <= a["measure_cost_pv"] < 200


def test_measures_remove_shortage(assessed):
    for rid in ("R1", "R2", "R3", "R7", "R8"):
        assert assessed[rid]["after"]["shortage"] == 0, rid
        assert assessed[rid]["after"]["min_reserve"] >= 45, rid


def test_r6_uses_extended_data(assessed):
    a = assessed["R6"]
    assert a["data_dir"] == "data_ext/loss_2pct"
    assert a["hit"]["losses"] > assessed["R7"]["baseline"]["losses"]


def test_all_preparations_fit_together(contexts):
    ctx = contexts.setdefault("", Context())
    plan = json.load(open(ROOT / "results" / "plans" / "v3-earth.json", encoding="utf-8"))
    for rid in ("R1", "R2", "R3", "R5"):
        plan = risks.apply_patch(plan, RISKS[rid]["measure"]["prep"])
    res = ctx.run(parse_plan(plan, ctx.case), "BASE")
    assert res["feasible"], [c["rule_id"] for c in res["constraint_checks"] if not c["ok"] and c["severity"] == "hard"]
    base = ctx.run(ctx.plan(ROOT / "results" / "plans" / "v3-earth.json"), "BASE")["totals"]["pv_total_mln"]
    assert res["totals"]["pv_total_mln"] - base < 250


def test_apply_patch_adds_and_removes_rows():
    plan = {"decisions": {"supply_orders": [{"source_id": "A", "year": 2035, "ordered_t": 10.0}], "capacity_reservations": [], "investments": [{"investment_id": "ZBO", "year": 2037}], "inventory_policy": {}}}
    out = risks.apply_patch(plan, {"orders": {"A": {"2035": 0, "2036": 5}}, "investments": {"ZBO": None, "ISRU": {"year": 2036}}})
    assert out["decisions"]["supply_orders"] == [{"source_id": "A", "year": 2036, "ordered_t": 5.0}]
    assert [i["investment_id"] for i in out["decisions"]["investments"]] == ["ISRU"]
    assert plan["decisions"]["supply_orders"][0]["ordered_t"] == 10.0
