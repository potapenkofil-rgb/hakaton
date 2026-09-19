import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import risks
from fuelhub.cli import Context

DOCS = {name: (ROOT / "docs" / f"{name}.md").read_text(encoding="utf-8") for name in ("STRESS_RESPONSE", "RISKS", "STAKEHOLDERS", "ARCHITECTURE", "UI_TEST")}


def fmt(x):
    return f"{int(round(x)):,}".replace(",", " ")


def signed(x):
    v = int(round(x))
    return ("+" if v >= 0 else "−") + fmt(abs(v))


@pytest.fixture(scope="module")
def ctx():
    return Context()


@pytest.fixture(scope="module")
def key(ctx):
    base = ctx.run(ctx.plan(ROOT / "results" / "plans" / "v3-earth.json"), "BASE")
    stress = ctx.run(ctx.plan(ROOT / "results" / "plans" / "v3-earth.json"), "MANDATORY_STRESS")
    resp = ctx.run(ctx.plan(ROOT / "results" / "plans" / "v3-earth-response.json"), "MANDATORY_STRESS")
    return base, stress, resp


def test_plan_numbers_in_docs(key):
    base, stress, resp = key
    pv_base, pv_stress, pv_resp = (r["totals"]["pv_total_mln"] for r in key)
    for name in ("STRESS_RESPONSE", "RISKS", "STAKEHOLDERS", "ARCHITECTURE"):
        assert fmt(pv_base) in DOCS[name], name
    for name in ("STRESS_RESPONSE", "RISKS", "STAKEHOLDERS", "UI_TEST"):
        assert fmt(pv_resp) in DOCS[name], name
    assert fmt(pv_stress) in DOCS["STRESS_RESPONSE"]
    assert f"{stress['totals']['shortage_total_t']:.0f} т" in DOCS["STRESS_RESPONSE"]
    assert fmt(pv_resp - pv_stress) in DOCS["STRESS_RESPONSE"]
    assert fmt(base["totals"]["total_cost_mln"]) in DOCS["ARCHITECTURE"] and fmt(base["totals"]["capex_total_mln"]) in DOCS["ARCHITECTURE"]
    for f in base["financial_breakdown"]:
        assert f"| {f['year']} | {fmt(f['procurement_mln'])} |" in DOCS["ARCHITECTURE"], f["year"]


def test_risk_numbers_in_docs():
    reg = json.load(open(ROOT / "configs" / "risks.json", encoding="utf-8"))
    contexts = {}
    for risk in reg["risks"]:
        a = risks.assess(reg, risk, contexts)
        cell = DOCS["RISKS"].split(f"| {risk['id']} |")[1].split("\n")[0]
        if a["measure_cost_pv"]:
            assert signed(a["measure_cost_pv"]) in cell, (risk["id"], cell)
        if risk["measure"].get("prep") or risk["measure"].get("response"):
            assert signed(a["after_pv_delta"]) in cell, (risk["id"], cell)
        else:
            assert signed(a["effect_pv"]) in cell, (risk["id"], cell)


def test_comparison_files_match_engine(ctx):
    import csv
    for name in ("comparison.csv", "comparison_demand.csv"):
        rows = list(csv.DictReader(open(ROOT / "results" / name, encoding="utf-8")))
        assert rows
        for r in rows:
            res = ctx.run(ctx.plan(ROOT / "results" / "plans" / f"{r['plan_id']}.json"), r["scenario_id"])
            assert float(r["pv_total_mln"]) == pytest.approx(res["totals"]["pv_total_mln"], abs=0.06), (name, r["plan_id"], r["scenario_id"])
            assert (r["feasible"] == "True") is res["feasible"]
