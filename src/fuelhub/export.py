from __future__ import annotations

import csv
import io
import json
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

TABLES = ("yearly_balance", "source_schedule", "inventory_trace", "financial_breakdown", "constraint_checks", "monthly_trace")
SKIP = {"scenario_id", "plan_id", "reserve_note", "reason", "name", "available_from", "lead_time", "order_by", "period", "storage_id"}


def unit_of(metric: str, default_units: dict) -> str:
    if metric.endswith("_t"):
        return "t"
    if metric.endswith("_mln"):
        return "mln"
    if metric.endswith("_mln_per_t"):
        return "mln/t"
    if "service_level" in metric or metric.endswith("_share") or metric == "delivery_share":
        return "share"
    if "days" in metric:
        return "days"
    if metric in ("discount_factor", "reliability"):
        return "share"
    if metric.endswith("_months") or metric == "available_months":
        return "months"
    if metric in ("ok", "feasible", "available"):
        return "bool"
    return default_units.get(metric, "")


def long_rows(result: dict) -> list[dict]:
    sid, pid, units = result["scenario_id"], result["plan_id"], result.get("units", {})
    out = []

    def add(year, entity, metric, value):
        if isinstance(value, bool):
            value = int(value)
        if value is None or isinstance(value, str):
            return
        out.append({"scenario_id": sid, "plan_id": pid, "year": year, "entity": entity,
                    "metric": metric, "value": value, "unit": unit_of(metric, units)})

    for r in result["yearly_balance"]:
        for k, v in r.items():
            if k not in SKIP and k != "year":
                add(r["year"], "hub", k, v)
    for r in result["source_schedule"]:
        for k, v in r.items():
            if k not in SKIP and k not in ("year", "source_id"):
                add(r["year"], r["source_id"], k, v)
    for r in result["inventory_trace"]:
        for k, v in r.items():
            if k not in SKIP and k != "year":
                add(r["year"], "storage:" + r["storage_id"], k, v)
    for r in result["financial_breakdown"]:
        for k, v in r.items():
            if k != "year":
                add(r["year"], "finance", k, v)
    for k, v in result["totals"].items():
        add("", "totals", k, v)
    for c in result["constraint_checks"]:
        entity = "check:" + c["rule_id"] + (":" + c["source_id"] if c.get("source_id") else "")
        for k in ("actual", "limit", "excess", "ok"):
            add(c["year"], entity, k, c[k])
    add("", "plan", "feasible", result["feasible"])
    return out


def write_long_csv(result: dict, path: Path | str) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["scenario_id", "plan_id", "year", "entity", "metric", "value", "unit"])
        w.writeheader()
        w.writerows(long_rows(result))
    return p


def _wide(result: dict, table: str) -> tuple[list[str], list[list]]:
    rows = result.get(table, [])
    if table == "totals":
        return ["metric", "value"], [[k, v] for k, v in result["totals"].items()]
    if table == "assumptions":
        items = result["meta"]["assumptions"]
        return ["name", "value", "unit", "source", "scope"], [[a[k] for k in ("name", "value", "unit", "source", "scope")] for a in items]
    if table == "risk_register":
        items = result.get("risk_register", [])
        cols = sorted({k for r in items for k in r}) if items else ["risk_id"]
        return cols, [[json.dumps(r.get(c), ensure_ascii=False) if isinstance(r.get(c), (dict, list)) else r.get(c) for c in cols] for r in items]
    cols: list[str] = []
    for r in rows:
        for k in r:
            if k not in cols:
                cols.append(k)
    return cols, [[r.get(c) for c in cols] for r in rows]


def write_tables(result: dict, directory: Path | str) -> list[Path]:
    d = Path(directory)
    d.mkdir(parents=True, exist_ok=True)
    out = []
    for table in TABLES + ("totals", "assumptions", "risk_register"):
        cols, rows = _wide(result, table)
        p = d / f"{table}.csv"
        with p.open("w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(cols)
            for r in rows:
                w.writerow(["" if v is None else (int(v) if isinstance(v, bool) else v) for v in r])
        out.append(p)
    (d / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    out.append(d / "result.json")
    return out


def _col(n: int) -> str:
    s = ""
    n += 1
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _cell(ref: str, v) -> str:
    if v is None or v == "":
        return ""
    if isinstance(v, bool):
        return f'<c r="{ref}" t="b"><v>{int(v)}</v></c>'
    if isinstance(v, (int, float)):
        if v != v or v in (float("inf"), float("-inf")):
            return f'<c r="{ref}" t="inlineStr"><is><t>{v}</t></is></c>'
        return f'<c r="{ref}"><v>{v!r}</v></c>'
    return f'<c r="{ref}" t="inlineStr"><is><t xml:space="preserve">{escape(str(v))}</t></is></c>'


def _sheet_xml(cols: list[str], rows: list[list]) -> str:
    lines = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
             '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>']
    all_rows = [cols] + rows
    for i, r in enumerate(all_rows, start=1):
        cells = "".join(_cell(f"{_col(j)}{i}", v) for j, v in enumerate(r))
        lines.append(f'<row r="{i}">{cells}</row>')
    lines.append("</sheetData></worksheet>")
    return "".join(lines)


def write_xlsx(result: dict, path: Path | str, sheets=None) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    names = list(sheets or (("summary",) + TABLES + ("totals", "assumptions", "risk_register")))
    content = []
    for name in names:
        if name == "summary":
            cols = ["field", "value"]
            rows = [["plan_id", result["plan_id"]], ["scenario_id", result["scenario_id"]], ["feasible", result["feasible"]],
                    ["engine_version", result["meta"]["engine_version"]], ["data_hash", result["meta"]["data_hash"]],
                    ["assumptions_reference", result["assumptions_reference"]]]
            for k, v in result["units"].items():
                rows.append([f"unit:{k}", v])
            for w in result.get("warnings", []):
                rows.append(["warning", w])
        else:
            cols, rows = _wide(result, name)
        content.append((name[:31], _sheet_xml(cols, rows)))
    with zipfile.ZipFile(p, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                   '<Default Extension="xml" ContentType="application/xml"/>'
                   '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                   + "".join(f'<Override PartName="/xl/worksheets/sheet{i + 1}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                             for i in range(len(content)))
                   + "</Types>")
        z.writestr("_rels/.rels",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
                   "</Relationships>")
        z.writestr("xl/workbook.xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                   'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
                   + "".join(f'<sheet name="{escape(n)}" sheetId="{i + 1}" r:id="rId{i + 1}"/>' for i, (n, _) in enumerate(content))
                   + "</sheets></workbook>")
        z.writestr("xl/_rels/workbook.xml.rels",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   + "".join(f'<Relationship Id="rId{i + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i + 1}.xml"/>'
                             for i in range(len(content)))
                   + "</Relationships>")
        for i, (_, xml) in enumerate(content):
            z.writestr(f"xl/worksheets/sheet{i + 1}.xml", xml)
    return p


def read_xlsx(path: Path | str) -> dict[str, list[list]]:
    import re
    with zipfile.ZipFile(path) as z:
        wb = z.read("xl/workbook.xml").decode("utf-8")
        names = re.findall(r'<sheet name="([^"]+)" sheetId="(\d+)"', wb)
        out = {}
        for name, sid in names:
            xml = z.read(f"xl/worksheets/sheet{sid}.xml").decode("utf-8")
            rows = []
            for row in re.findall(r"<row r=\"\d+\">(.*?)</row>", xml):
                cells = []
                for ref, t, body in re.findall(r'<c r="([A-Z]+\d+)"(?: t="(\w+)")?>(.*?)</c>', row):
                    if t == "inlineStr":
                        m = re.search(r"<t[^>]*>(.*?)</t>", body)
                        cells.append(m.group(1) if m else "")
                    elif t == "b":
                        cells.append(body.strip("<v>/") == "1")
                    else:
                        v = re.search(r"<v>(.*?)</v>", body).group(1)
                        cells.append(int(v) if re.fullmatch(r"-?\d+", v) else float(v))
                rows.append(cells)
            out[name] = rows
    return out
