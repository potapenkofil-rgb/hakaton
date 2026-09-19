from __future__ import annotations

import json
import mimetypes
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import export
from .cli import Context, RESULTS_DIR, inputs_payload
from .data import ROOT
from .plan import PlanError, parse_plan, save_plan

STATIC_DIR = ROOT / "app" / "static"
PLANS_DIR = RESULTS_DIR / "plans"


def safe_id(plan_id: str) -> str:
    s = re.sub(r"[^A-Za-z0-9._-]+", "-", plan_id.strip()).strip("-.")
    if not s:
        raise PlanError([{"path": "plan_id", "message": "имя плана должно содержать буквы или цифры"}])
    return s


def list_plans() -> list[dict]:
    out = []
    for p in sorted(PLANS_DIR.glob("*.json")):
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
            out.append({"plan_id": raw.get("plan_id", p.stem), "label": raw.get("label", ""),
                        "scenario_id": raw.get("scenario_id", ""), "file": p.name})
        except (json.JSONDecodeError, UnicodeDecodeError):
            out.append({"plan_id": p.stem, "label": "файл повреждён", "scenario_id": "", "file": p.name})
    return out


class Api:
    def __init__(self, ctx: Context):
        self.ctx = ctx

    def inputs(self) -> dict:
        return inputs_payload(self.ctx) | {"plans": list_plans(), "plans_dir": str(PLANS_DIR)}

    def calculate(self, body: dict) -> dict:
        case = self.ctx.with_overrides(body.get("overrides"))
        plan = parse_plan(body.get("plan", body), case)
        return self.ctx.run(plan, body.get("scenario_id"), case)

    def compare(self, body: dict) -> dict:
        case = self.ctx.with_overrides(body.get("overrides"))
        plan = parse_plan(body.get("plan", body), case)
        return self.ctx.compare(plan, body.get("scenarios") or ["BASE", "MANDATORY_STRESS"], case)

    def save(self, body: dict) -> dict:
        plan = parse_plan(body.get("plan", body), self.ctx.case)
        path = save_plan(plan, PLANS_DIR / f"{safe_id(plan.plan_id)}.json")
        return {"saved": path.name, "plan_id": plan.plan_id, "plans": list_plans()}

    def load(self, name: str) -> dict:
        path = PLANS_DIR / f"{safe_id(name)}.json"
        if not path.exists():
            raise KeyError(name)
        return json.loads(path.read_text(encoding="utf-8"))

    def export(self, body: dict, fmt: str, scenario_id: str | None) -> tuple[bytes, str, str]:
        case = self.ctx.with_overrides(body.get("overrides"))
        plan = parse_plan(body.get("plan", body), case)
        res = self.ctx.run(plan, scenario_id or body.get("scenario_id"), case)
        name = f"{safe_id(plan.plan_id)}_{res['scenario_id']}"
        tmp = RESULTS_DIR / "exports"
        tmp.mkdir(parents=True, exist_ok=True)
        if fmt == "xlsx":
            p = export.write_xlsx(res, tmp / f"{name}.xlsx")
            return p.read_bytes(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", p.name
        if fmt == "json":
            p = tmp / f"{name}.json"
            p.write_text(json.dumps(res, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            return p.read_bytes(), "application/json", p.name
        p = export.write_long_csv(res, tmp / f"{name}.csv")
        return p.read_bytes(), "text/csv; charset=utf-8", p.name


def make_handler(api: Api):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass

        def send_json(self, obj, status=200):
            data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def send_file(self, data: bytes, ctype: str, name: str | None = None):
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            if name:
                self.send_header("Content-Disposition", f'attachment; filename="{name}"')
            self.end_headers()
            self.wfile.write(data)

        def body(self) -> dict:
            n = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(n) if n else b""
            if not raw:
                raise PlanError([{"path": "", "message": "пустой запрос"}])
            try:
                return json.loads(raw.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                raise PlanError([{"path": "", "message": f"тело запроса не JSON: {e}"}])

        def do_GET(self):
            url = urlparse(self.path)
            q = parse_qs(url.query)
            try:
                if url.path == "/api/inputs":
                    return self.send_json(api.inputs())
                if url.path == "/api/plans":
                    return self.send_json({"plans": list_plans()})
                m = re.fullmatch(r"/api/plans/([^/]+)", url.path)
                if m:
                    return self.send_json(api.load(m.group(1)))
                m = re.fullmatch(r"/api/export/([^/]+)", url.path)
                if m:
                    data, ctype, name = api.export(api.load(m.group(1)), q.get("format", ["csv"])[0], q.get("scenario", [None])[0])
                    return self.send_file(data, ctype, name)
                return self.static(url.path)
            except PlanError as e:
                return self.send_json(e.to_dict(), 400)
            except KeyError as e:
                return self.send_json({"error": "NOT_FOUND", "message": f"нет такого плана: {e}"}, 404)

        def do_POST(self):
            url = urlparse(self.path)
            q = parse_qs(url.query)
            try:
                body = self.body()
                if url.path == "/api/calculate":
                    return self.send_json(api.calculate(body))
                if url.path == "/api/compare":
                    return self.send_json(api.compare(body))
                if url.path == "/api/plans":
                    return self.send_json(api.save(body))
                if url.path == "/api/export":
                    data, ctype, name = api.export(body, q.get("format", ["csv"])[0], q.get("scenario", [None])[0])
                    return self.send_file(data, ctype, name)
                return self.send_json({"error": "NOT_FOUND", "message": f"нет такого пути: {url.path}"}, 404)
            except PlanError as e:
                return self.send_json(e.to_dict(), 400)

        def static(self, path: str):
            rel = "index.html" if path in ("", "/") else path.lstrip("/")
            target = (STATIC_DIR / rel).resolve()
            if not str(target).startswith(str(STATIC_DIR.resolve())) or not target.is_file():
                return self.send_json({"error": "NOT_FOUND", "message": f"нет файла {path}"}, 404)
            ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
            if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
                ctype += "; charset=utf-8"
            return self.send_file(target.read_bytes(), ctype)

    return Handler


def serve(host: str = "127.0.0.1", port: int = 8765, ctx: Context | None = None):
    api = Api(ctx or Context())
    PLANS_DIR.mkdir(parents=True, exist_ok=True)
    httpd = ThreadingHTTPServer((host, port), make_handler(api))
    print(f"Топливный узел: http://{host}:{port}/  (Ctrl+C — остановить)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
