from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass, field, replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
CONFIG_DIR = ROOT / "configs"

WEEKS_PER_MONTH = 52 / 12


@dataclass(frozen=True)
class Demand:
    year: int
    total: float
    critical: float
    low_total: float
    high_total: float

    @property
    def critical_share(self) -> float:
        return self.critical / self.total if self.total else 0.0


@dataclass(frozen=True)
class Source:
    id: str
    name: str
    capacity: float
    price: float
    reservation_rate: float
    top_share: float
    lead_time_min: float
    lead_time_max: float
    lead_time_unit: str
    reliability: str
    available_from: int | None
    notes: str

    @property
    def lead_time_months(self) -> float:
        if self.lead_time_unit == "week":
            return self.lead_time_max / WEEKS_PER_MONTH
        return float(self.lead_time_max)

    @property
    def needs_reservation(self) -> bool:
        return self.reservation_rate > 0 or self.top_share > 0

    def reliability_for(self, year: int, first_operating_year: int | None = None) -> float | None:
        parts = dict(p.split(":") for p in self.reliability.split(";") if p)
        if "constant" in parts:
            return float(parts["constant"])
        if str(year) in parts:
            return float(parts[str(year)])
        if "first_operating_year" in parts and first_operating_year is not None:
            key = "first_operating_year" if year == first_operating_year else "later"
            return float(parts[key])
        return None


@dataclass(frozen=True)
class Storage:
    id: str
    name: str
    capacity: float
    loss_rate: float
    holding_cost: float
    capex: float
    fixed_opex: float
    available_from: int


@dataclass(frozen=True)
class Investment:
    id: str
    name: str
    option_fee: float
    exercise_cost: float
    total_capex: float
    fixed_opex: float
    commissioning_rule: str
    notes: str


@dataclass(frozen=True)
class Constraint:
    id: str
    metric: str
    op: str
    value: float
    unit: str
    period: str
    scenario: str
    severity: str
    description: str


@dataclass(frozen=True)
class CaseData:
    years: tuple[int, ...]
    demand: dict[int, Demand]
    sources: dict[str, Source]
    storages: dict[str, Storage]
    investments: dict[str, Investment]
    constraints: tuple[Constraint, ...]
    data_hash: str
    data_dir: str
    overrides: dict = field(default_factory=dict)

    @property
    def first_year(self) -> int:
        return self.years[0]

    @property
    def last_year(self) -> int:
        return self.years[-1]

    def source_id(self, name_or_id: str) -> str | None:
        if name_or_id in self.sources:
            return name_or_id
        for s in self.sources.values():
            if s.name == name_or_id:
                return s.id
        return None


@dataclass(frozen=True)
class Assumption:
    name: str
    value: object
    unit: str
    source: str
    scope: str


class Assumptions:
    def __init__(self, items: list[Assumption], path: str = ""):
        self.items = items
        self.path = path
        self._by_name = {a.name: a for a in items}

    def __getitem__(self, name: str):
        if name not in self._by_name:
            raise KeyError(f"нет допущения {name} в {self.path or 'assumptions'}")
        return self._by_name[name].value

    def get(self, name: str, default=None):
        a = self._by_name.get(name)
        return default if a is None else a.value

    def to_list(self) -> list[dict]:
        return [a.__dict__ for a in self.items]


def _num(value: str) -> float:
    return float(value) if value not in ("", None) else 0.0


def _opt_year(value: str) -> int | None:
    return int(value) if value.strip() else None


def _read(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def load_case(data_dir: Path | str = DATA_DIR) -> CaseData:
    d = Path(data_dir)
    demand = {}
    for r in _read(d / "demand.csv"):
        y = int(r["year"])
        demand[y] = Demand(y, _num(r["base_total_t"]), _num(r["base_critical_t"]),
                           _num(r["low_total_t"]), _num(r["high_total_t"]))
    sources = {}
    for r in _read(d / "supply_sources.csv"):
        sources[r["source_id"]] = Source(
            r["source_id"], r["name"], _num(r["capacity_t_per_year"]), _num(r["variable_cost_mln_per_t"]),
            _num(r["reservation_rate_mln_per_t_year_capacity"]), _num(r["take_or_pay_share"]),
            _num(r["lead_time_min_value"]), _num(r["lead_time_max_value"]), r["lead_time_unit"],
            r["reliability_profile"], _opt_year(r["available_from_year"]), r.get("notes", ""))
    storages = {}
    for r in _read(d / "storage_options.csv"):
        storages[r["storage_id"]] = Storage(
            r["storage_id"], r["name"], _num(r["capacity_t"]), _num(r["loss_rate_on_throughput"]),
            _num(r["holding_cost_mln_per_t_year"]), _num(r["capex_mln"]), _num(r["fixed_opex_mln_per_year"]),
            int(r["available_from_year"]))
    investments = {}
    for r in _read(d / "investment_options.csv"):
        investments[r["investment_id"]] = Investment(
            r["investment_id"], r["name"], _num(r["option_fee_mln"]), _num(r["exercise_cost_mln"]),
            _num(r["total_capex_mln"]), _num(r["fixed_opex_mln_per_year"]), r["commissioning_rule"], r.get("notes", ""))
    constraints = tuple(
        Constraint(r["constraint_id"], r["metric"], r["operator"], _num(r["value"]), r["unit"],
                   r["period"], r["scenario"], r["severity"], r.get("description", ""))
        for r in _read(d / "constraints.csv"))
    h = hashlib.sha256()
    for name in sorted(p.name for p in d.glob("*.csv")):
        h.update(name.encode())
        h.update((d / name).read_bytes())
    years = tuple(sorted(demand))
    return CaseData(years, demand, sources, storages, investments, constraints, h.hexdigest()[:16], str(d))


OVERRIDABLE = {
    "sources": ("capacity", "price", "reservation_rate", "top_share"),
    "storages": ("capacity", "loss_rate", "holding_cost", "capex", "fixed_opex"),
    "demand": ("total", "critical"),
}


def with_overrides(case: CaseData, overrides: dict | None) -> tuple[CaseData, list[dict]]:
    if not overrides:
        return case, []
    errors = []
    tables = {"sources": dict(case.sources), "storages": dict(case.storages), "demand": dict(case.demand)}
    clean = {}
    for kind, items in overrides.items():
        if kind not in OVERRIDABLE:
            errors.append({"path": f"overrides.{kind}", "message": f"неизвестный раздел; есть {', '.join(OVERRIDABLE)}"})
            continue
        if not isinstance(items, dict):
            errors.append({"path": f"overrides.{kind}", "message": "ожидается объект {id: {поле: значение}}"})
            continue
        table = tables[kind]
        for key, fields in items.items():
            k = int(key) if kind == "demand" and str(key).lstrip("-").isdigit() else key
            if k not in table:
                errors.append({"path": f"overrides.{kind}.{key}", "message": f"нет такого элемента; есть {', '.join(map(str, table))}"})
                continue
            if not isinstance(fields, dict):
                errors.append({"path": f"overrides.{kind}.{key}", "message": "ожидается объект {поле: значение}"})
                continue
            changes = {}
            for name, value in fields.items():
                if name not in OVERRIDABLE[kind]:
                    errors.append({"path": f"overrides.{kind}.{key}.{name}", "message": f"поле нельзя менять; можно {', '.join(OVERRIDABLE[kind])}"})
                elif isinstance(value, bool) or not isinstance(value, (int, float)) or value != value or value < 0:
                    errors.append({"path": f"overrides.{kind}.{key}.{name}", "message": f"нужно число не меньше нуля, получено {value!r}"})
                elif value != getattr(table[k], name):
                    changes[name] = float(value)
            if changes:
                table[k] = replace(table[k], **changes)
                clean.setdefault(kind, {})[str(key)] = changes
    if errors or not clean:
        return case, errors
    h = hashlib.sha256(json.dumps(clean, sort_keys=True).encode()).hexdigest()[:8]
    return replace(case, sources=tables["sources"], storages=tables["storages"], demand=tables["demand"],
                   data_hash=f"{case.data_hash}+{h}", overrides=clean), []


def load_assumptions(path: Path | str = CONFIG_DIR / "assumptions.json") -> Assumptions:
    p = Path(path)
    raw = json.loads(p.read_text(encoding="utf-8"))
    items = [Assumption(a["name"], a["value"], a.get("unit", ""), a.get("source", ""), a.get("scope", ""))
             for a in raw.get("assumptions", [])]
    return Assumptions(items, str(p))
