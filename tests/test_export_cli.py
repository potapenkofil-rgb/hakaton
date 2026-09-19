import csv
import json
import subprocess
import sys

import pytest

from fuelhub import ROOT
from fuelhub.cli import Context, main
from fuelhub.export import long_rows, read_xlsx, write_long_csv, write_tables, write_xlsx

from conftest import run, year_row

PLAN = ROOT / "results" / "plans" / "base-v1.json"


@pytest.fixture(scope="module")
def result(case, scenarios, assumptions, base_plan_dict):
    return run(case, scenarios, assumptions, base_plan_dict, "MANDATORY_STRESS")


def test_long_csv_matches_result(result, tmp_path):
    p = write_long_csv(result, tmp_path / "out.csv")
    with p.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    assert rows[0].keys() == {"scenario_id", "plan_id", "year", "entity", "metric", "value", "unit"}
    assert all(r["scenario_id"] == "MANDATORY_STRESS" and r["plan_id"] == "base-v1" for r in rows)
    served = {int(r["year"]): float(r["value"]) for r in rows if r["entity"] == "hub" and r["metric"] == "served_total_t"}
    assert served == {r["year"]: r["served_total_t"] for r in result["yearly_balance"]}
    pv = [float(r["value"]) for r in rows if r["entity"] == "finance" and r["metric"] == "pv_mln"]
    assert pv == [f["pv_mln"] for f in result["financial_breakdown"]]
    a38 = [r for r in rows if r["entity"] == "A" and r["year"] == "2038" and r["metric"] == "variable_payment_mln"]
    assert float(a38[0]["value"]) == year_row(result, "source_schedule", 2038, source_id="A")["variable_payment_mln"]
    assert a38[0]["unit"] == "mln"
    units = {r["metric"]: r["unit"] for r in rows}
    assert units["served_total_t"] == "t" and units["service_level_total"] == "share" and units["reserve_equivalent_days"] == "days"
    checks = [r for r in rows if r["entity"].startswith("check:RESERVE_45D") and r["metric"] == "ok"]
    assert len(checks) == 6 and sorted(r["value"] for r in checks) == ["0", "0", "1", "1", "1", "1"]
    total = [r for r in rows if r["entity"] == "totals" and r["metric"] == "total_cost_mln"][0]
    assert float(total["value"]) == result["totals"]["total_cost_mln"]


def test_long_rows_have_no_strings(result):
    for r in long_rows(result):
        assert isinstance(r["value"], (int, float))


def test_tables_and_json(result, tmp_path):
    files = write_tables(result, tmp_path / "tables")
    names = {p.name for p in files}
    assert {"yearly_balance.csv", "source_schedule.csv", "constraint_checks.csv", "financial_breakdown.csv",
            "totals.csv", "assumptions.csv", "result.json", "monthly_trace.csv"} <= names
    with (tmp_path / "tables" / "yearly_balance.csv").open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    assert [int(r["year"]) for r in rows] == [2035, 2036, 2037, 2038, 2039, 2040]
    assert float(rows[4]["shortage_total_t"]) == year_row(result, "yearly_balance", 2039)["shortage_total_t"]
    again = json.loads((tmp_path / "tables" / "result.json").read_text(encoding="utf-8"))
    assert again == json.loads(json.dumps(result))


def test_xlsx_roundtrip(result, tmp_path):
    p = write_xlsx(result, tmp_path / "out.xlsx")
    sheets = read_xlsx(p)
    assert "yearly_balance" in sheets and "constraint_checks" in sheets and "summary" in sheets
    header, *rows = sheets["yearly_balance"]
    col = header.index("closing_stock_t")
    assert [r[col] for r in rows] == [r["closing_stock_t"] for r in result["yearly_balance"]]
    assert sheets["summary"][1][1] == "base-v1"
    fin_header, *fin_rows = sheets["financial_breakdown"]
    assert fin_rows[0][fin_header.index("capex_mln")] == 90


def test_context_compare(case):
    ctx = Context()
    plan = ctx.plan(PLAN)
    cmp = ctx.compare(plan, ["BASE", "MANDATORY_STRESS"])
    assert cmp["feasible"] == {"BASE": True, "MANDATORY_STRESS": False}
    row = [r for r in cmp["yearly"] if r["year"] == 2039 and r["metric"] == "shortage_total_t"][0]
    assert row["BASE"] == 0 and row["MANDATORY_STRESS"] > 0 and row["delta:MANDATORY_STRESS"] == row["MANDATORY_STRESS"]
    pv = [r for r in cmp["totals"] if r["metric"] == "pv_total_mln"][0]
    assert pv["delta:MANDATORY_STRESS"] == pytest.approx(pv["MANDATORY_STRESS"] - pv["BASE"])
    assert cmp["violations"]["BASE"] == [] and cmp["violations"]["MANDATORY_STRESS"]


def test_cli_overrides(tmp_path, capsys):
    o = tmp_path / "o.json"
    o.write_text(json.dumps({"sources": {"A": {"price": 7.0}}}), encoding="utf-8")
    assert main(["--overrides", str(o), "calc", str(PLAN), "--quiet", "--out", str(tmp_path / "r.json")]) == 0
    res = json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))
    assert res["meta"]["overrides"] == {"sources": {"A": {"price": 7.0}}}
    assert main(["--overrides", str(o), "export", str(PLAN), "--format", "xlsx", "--out", str(tmp_path / "e.xlsx")]) == 0
    summary = read_xlsx(tmp_path / "e.xlsx")["summary"]
    assert ["override:sources.A.price", 7.0] in [list(r) for r in summary]
    o.write_text(json.dumps({"sources": {"A": {"price": "seven"}}}), encoding="utf-8")
    assert main(["--overrides", str(o), "calc", str(PLAN), "--quiet"]) == 2
    assert "overrides.sources.A.price" in capsys.readouterr().err


def test_cli_calc_and_export(tmp_path, capsys):
    assert main(["calc", str(PLAN), "--out", str(tmp_path / "r.json")]) == 0
    out = capsys.readouterr().out
    assert "исполним" in out and "Нарушений нет" in out
    res = json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))
    assert res["feasible"] is True
    assert main(["calc", str(PLAN), "--scenario", "MANDATORY_STRESS", "--quiet"]) == 0
    assert main(["export", str(PLAN), "--format", "csv", "--out", str(tmp_path / "e.csv")]) == 0
    assert main(["export", str(PLAN), "--format", "xlsx", "--out", str(tmp_path / "e.xlsx"), "--scenario", "MANDATORY_STRESS"]) == 0
    assert main(["export", str(PLAN), "--format", "tables", "--out", str(tmp_path / "t")]) == 0
    assert (tmp_path / "t" / "yearly_balance.csv").exists()
    assert main(["validate", str(PLAN)]) == 0
    assert main(["scenarios"]) == 0
    assert "MANDATORY_STRESS" in capsys.readouterr().out
    assert main(["compare", str(PLAN), "--out", str(tmp_path / "c.json")]) == 0
    assert json.loads((tmp_path / "c.json").read_text(encoding="utf-8"))["feasible"]["MANDATORY_STRESS"] is False


def test_cli_inputs(capsys):
    assert main(["inputs"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert [s["id"] for s in payload["sources"]] == ["A", "B", "C", "D", "E"]
    assert payload["sources"][4]["lead_time_months"] == pytest.approx(6 / (52 / 12))
    assert {s["scenario_id"] for s in payload["scenarios"]} >= {"BASE", "MANDATORY_STRESS"}


def test_cli_invalid_plan_exit_2(tmp_path, capsys):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"plan_id": "x", "scenario_id": "BASE", "decisions": {
        "supply_orders": [{"source_id": "Q", "year": 2035, "ordered_t": 1}], "capacity_reservations": [], "investments": [],
        "inventory_policy": {}}}), encoding="utf-8")
    assert main(["calc", str(bad)]) == 2
    assert "неизвестный канал Q" in capsys.readouterr().err
    assert main(["calc", str(PLAN), "--scenario", "NOPE"]) == 2


def test_cli_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        main(["calc", str(tmp_path / "none.json")])


def test_cli_and_api_agree(tmp_path, case, scenarios, assumptions, base_plan_dict):
    main(["calc", str(PLAN), "--quiet", "--out", str(tmp_path / "cli.json")])
    from_cli = json.loads((tmp_path / "cli.json").read_text(encoding="utf-8"))
    from_api = json.loads(json.dumps(run(case, scenarios, assumptions, base_plan_dict)))
    assert from_cli == from_api


def test_module_entry_point(tmp_path):
    env = {"PYTHONPATH": str(ROOT / "src"), "PYTHONIOENCODING": "utf-8"}
    import os
    proc = subprocess.run([sys.executable, "-m", "fuelhub", "calc", str(PLAN), "--quiet", "--out", str(tmp_path / "m.json")],
                          capture_output=True, text=True, env={**os.environ, **env}, cwd=ROOT)
    assert proc.returncode == 0, proc.stderr
    assert (tmp_path / "m.json").exists()


def test_two_exports_byte_identical(result, tmp_path):
    a = write_long_csv(result, tmp_path / "a.csv").read_bytes()
    b = write_long_csv(result, tmp_path / "b.csv").read_bytes()
    assert a == b
