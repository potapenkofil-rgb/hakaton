import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from fuelhub import ROOT
from fuelhub.cli import Context
from fuelhub.export import read_xlsx
from fuelhub.server import Api, PLANS_DIR, make_handler, safe_id

from conftest import make_plan


@pytest.fixture(scope="module")
def server():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(Api(Context())))
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def call(base, path, body=None, raw=False):
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(base + path, data=data, headers={"Content-Type": "application/json"} if data else {})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            payload = r.read()
            return r.status, (payload if raw else json.loads(payload)), dict(r.headers)
    except urllib.error.HTTPError as e:
        payload = e.read()
        return e.code, json.loads(payload), dict(e.headers)


@pytest.fixture(scope="module")
def base_plan():
    return json.loads((ROOT / "results" / "plans" / "base-v1.json").read_text(encoding="utf-8"))


def test_index_and_static(server):
    status, body, headers = call(server, "/", raw=True)
    assert status == 200 and b"<title>" in body and headers["Cache-Control"] == "no-store"
    assert call(server, "/app.js", raw=True)[0] == 200
    assert call(server, "/styles.css", raw=True)[0] == 200
    assert call(server, "/nothing.html")[0] == 404
    assert call(server, "/../pyproject.toml")[0] == 404


def test_inputs(server):
    status, body, _ = call(server, "/api/inputs")
    assert status == 200
    assert [s["id"] for s in body["sources"]] == ["A", "B", "C", "D", "E"]
    assert {s["scenario_id"] for s in body["scenarios"]} >= {"BASE", "MANDATORY_STRESS"}
    assert any(p["plan_id"] == "base-v1" for p in body["plans"])
    assert body["data_hash"]


def test_calculate_matches_cli(server, base_plan, case, scenarios, assumptions):
    from conftest import run
    status, body, _ = call(server, "/api/calculate", {"plan": base_plan, "scenario_id": "MANDATORY_STRESS"})
    assert status == 200 and body["scenario_id"] == "MANDATORY_STRESS" and body["feasible"] is False
    assert body == json.loads(json.dumps(run(case, scenarios, assumptions, base_plan, "MANDATORY_STRESS")))
    status, body, _ = call(server, "/api/calculate", base_plan)
    assert status == 200 and body["scenario_id"] == "BASE" and body["feasible"] is True


def test_calculate_with_overrides(server, base_plan):
    over = {"sources": {"A": {"price": 7.0}}, "demand": {"2040": {"total": 420}}}
    status, body, _ = call(server, "/api/calculate", {"plan": base_plan, "overrides": over})
    assert status == 200 and body["meta"]["overrides"] == {"sources": {"A": {"price": 7.0}}, "demand": {"2040": {"total": 420.0}}}
    assert "+" in body["meta"]["data_hash"]
    status, plain, _ = call(server, "/api/calculate", {"plan": base_plan})
    assert plain["meta"]["overrides"] == {} and body["totals"]["pv_total_mln"] > plain["totals"]["pv_total_mln"]
    status, cmp, _ = call(server, "/api/compare", {"plan": base_plan, "overrides": over})
    assert status == 200 and cmp["results"]["BASE"]["meta"]["overrides"] == body["meta"]["overrides"]
    status, err, _ = call(server, "/api/calculate", {"plan": base_plan, "overrides": {"sources": {"A": {"price": -5}}}})
    assert status == 400 and err["details"][0]["path"] == "overrides.sources.A.price"
    status, raw, headers = call(server, "/api/export?format=csv", {"plan": base_plan, "overrides": over}, raw=True)
    assert status == 200 and b"override:sources:A" in raw


def test_calculate_invalid_plan_400(server):
    status, body, _ = call(server, "/api/calculate", {"plan": make_plan(orders={"A": {2035: -1}})})
    assert status == 400 and body["error"] == "INVALID_PLAN"
    assert body["details"][0]["path"] == "decisions.supply_orders[0].ordered_t"
    status, body, _ = call(server, "/api/calculate", {"plan": make_plan(), "scenario_id": "NOPE"})
    assert status == 400 and "NOPE" in body["details"][0]["message"]


def test_bad_json_body(server):
    req = urllib.request.Request(server + "/api/calculate", data=b"{oops", headers={"Content-Type": "application/json"})
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(req, timeout=10)
    assert e.value.code == 400
    assert "JSON" in json.loads(e.value.read())["details"][0]["message"]


def test_compare(server, base_plan):
    status, body, _ = call(server, "/api/compare", {"plan": base_plan})
    assert status == 200 and body["scenarios"] == ["BASE", "MANDATORY_STRESS"]
    assert body["feasible"] == {"BASE": True, "MANDATORY_STRESS": False}
    assert any(r["metric"] == "shortage_total_t" and r["year"] == 2039 and r["MANDATORY_STRESS"] > 0 for r in body["yearly"])


def test_save_load_roundtrip(server, base_plan):
    plan = json.loads(json.dumps(base_plan))
    plan["plan_id"] = "pytest-tmp plan"
    status, body, _ = call(server, "/api/plans", {"plan": plan})
    assert status == 200 and body["saved"] == "pytest-tmp-plan.json"
    assert any(p["plan_id"] == "pytest-tmp plan" for p in body["plans"])
    status, again, _ = call(server, "/api/plans/pytest-tmp-plan")
    assert status == 200 and again["decisions"] == plan["decisions"]
    status, listing, _ = call(server, "/api/plans")
    assert any(p["file"] == "pytest-tmp-plan.json" for p in listing["plans"])
    (PLANS_DIR / "pytest-tmp-plan.json").unlink()
    assert call(server, "/api/plans/pytest-tmp-plan")[0] == 404


def test_save_rejects_invalid(server):
    status, body, _ = call(server, "/api/plans", {"plan": make_plan(reservations={"Z": {2035: 1}})})
    assert status == 400 and body["error"] == "INVALID_PLAN"
    assert not (PLANS_DIR / "t.json").exists()


def test_export_csv_xlsx_json(server, base_plan, tmp_path):
    status, body, headers = call(server, "/api/export?format=csv&scenario=MANDATORY_STRESS", {"plan": base_plan}, raw=True)
    assert status == 200 and headers["Content-Type"].startswith("text/csv")
    assert 'filename="base-v1_MANDATORY_STRESS.csv"' in headers["Content-Disposition"]
    text = body.decode("utf-8")
    assert text.startswith("scenario_id,plan_id,year,entity,metric,value,unit")
    assert "MANDATORY_STRESS,base-v1,2039,hub,shortage_total_t," in text
    status, body, headers = call(server, "/api/export?format=xlsx", {"plan": base_plan}, raw=True)
    assert status == 200 and headers["Content-Type"].endswith("sheet")
    p = tmp_path / "e.xlsx"
    p.write_bytes(body)
    assert "yearly_balance" in read_xlsx(p)
    status, body, _ = call(server, "/api/export?format=json", {"plan": base_plan})
    assert status == 200 and body["plan_id"] == "base-v1"
    status, body, _ = call(server, "/api/export/base-v1?format=csv", raw=True)
    assert status == 200 and body.startswith(b"scenario_id")
    assert call(server, "/api/export/missing-plan?format=csv")[0] == 404


def test_unknown_post_path(server):
    assert call(server, "/api/nothing", {"plan": {}})[0] == 404


def test_safe_id():
    assert safe_id("base v1/../x") == "base-v1-..-x"
    assert "/" not in safe_id("a/b\\c") and "\\" not in safe_id("a/b\\c")
    assert safe_id("  my plan  ") == "my-plan"
    from fuelhub.plan import PlanError
    with pytest.raises(PlanError):
        safe_id("///")
