from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .data import CaseData


class PlanError(Exception):
    def __init__(self, details: list[dict]):
        super().__init__("; ".join(f"{d['path']}: {d['message']}" for d in details))
        self.details = details

    def to_dict(self) -> dict:
        return {"error": "INVALID_PLAN", "details": self.details}


@dataclass(frozen=True)
class Order:
    source_id: str
    year: int
    ordered_t: float


@dataclass(frozen=True)
class Reservation:
    source_id: str
    year: int
    reserved_t: float


@dataclass(frozen=True)
class InvestmentDecision:
    investment_id: str
    year: int | None = None
    option_year: int | None = None
    exercise_year: int | None = None
    financing_years: tuple[int, ...] = ()

    def to_dict(self) -> dict:
        d = {"investment_id": self.investment_id}
        if self.year is not None:
            d["year"] = self.year
        if self.option_year is not None:
            d["option_year"] = self.option_year
        if self.exercise_year is not None:
            d["exercise_year"] = self.exercise_year
        if self.financing_years:
            d["financing_years"] = list(self.financing_years)
        return d


@dataclass(frozen=True)
class InventoryPolicy:
    initial_stock_t: float = 0.0
    initial_stock_source_id: str | None = None
    initial_stock_cost_mln: float = 0.0
    storage_id: str = "BASE"

    def to_dict(self) -> dict:
        return {
            "initial_stock_t": self.initial_stock_t,
            "initial_stock_source_id": self.initial_stock_source_id,
            "initial_stock_cost_mln": self.initial_stock_cost_mln,
            "storage_id": self.storage_id,
        }


@dataclass(frozen=True)
class Plan:
    plan_id: str
    scenario_id: str
    orders: tuple[Order, ...]
    reservations: tuple[Reservation, ...]
    investments: tuple[InvestmentDecision, ...]
    inventory: InventoryPolicy
    label: str = ""

    def ordered(self, source_id: str, year: int) -> float:
        return sum(o.ordered_t for o in self.orders if o.source_id == source_id and o.year == year)

    def reserved(self, source_id: str, year: int) -> float:
        return sum(r.reserved_t for r in self.reservations if r.source_id == source_id and r.year == year)

    def investment(self, investment_id: str) -> InvestmentDecision | None:
        for inv in self.investments:
            if inv.investment_id == investment_id:
                return inv
        return None

    def to_dict(self) -> dict:
        d = {
            "plan_id": self.plan_id,
            "scenario_id": self.scenario_id,
            "decisions": {
                "supply_orders": [{"source_id": o.source_id, "year": o.year, "ordered_t": o.ordered_t} for o in self.orders],
                "capacity_reservations": [{"source_id": r.source_id, "year": r.year, "reserved_capacity_t": r.reserved_t}
                                          for r in self.reservations],
                "investments": [i.to_dict() for i in self.investments],
                "inventory_policy": self.inventory.to_dict(),
            },
        }
        if self.label:
            d["label"] = self.label
        return d


class _Checker:
    def __init__(self, case: CaseData, scenario_ids):
        self.case = case
        self.scenario_ids = set(scenario_ids) if scenario_ids is not None else None
        self.errors: list[dict] = []

    def fail(self, path: str, message: str):
        self.errors.append({"path": path, "message": message})

    def number(self, obj: dict, key: str, path: str, required: bool = True, minimum: float = 0.0) -> float | None:
        if key not in obj:
            if required:
                self.fail(f"{path}.{key}", "поле обязательно")
            return None
        v = obj[key]
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            self.fail(f"{path}.{key}", f"ожидалось число, получено {v!r}")
            return None
        if v < minimum:
            self.fail(f"{path}.{key}", f"отрицательный объём: {v}")
            return None
        return float(v)

    def year(self, obj: dict, key: str, path: str, required: bool = True) -> int | None:
        if key not in obj:
            if required:
                self.fail(f"{path}.{key}", "поле обязательно")
            return None
        v = obj[key]
        if isinstance(v, bool) or not isinstance(v, int):
            self.fail(f"{path}.{key}", f"ожидался год, получено {v!r}")
            return None
        if v < self.case.first_year or v > self.case.last_year:
            self.fail(f"{path}.{key}", f"год {v} вне горизонта {self.case.first_year}–{self.case.last_year}")
            return None
        return v

    def source(self, obj: dict, path: str) -> str | None:
        sid = obj.get("source_id")
        if sid is None:
            self.fail(f"{path}.source_id", "поле обязательно")
            return None
        if sid not in self.case.sources:
            self.fail(f"{path}.source_id", f"неизвестный канал {sid}; есть {', '.join(self.case.sources)}")
            return None
        return sid


def parse_plan(raw: dict, case: CaseData, scenario_ids=None) -> Plan:
    c = _Checker(case, scenario_ids)
    if not isinstance(raw, dict):
        raise PlanError([{"path": "", "message": "план должен быть объектом JSON"}])
    plan_id = raw.get("plan_id")
    if not isinstance(plan_id, str) or not plan_id.strip():
        c.fail("plan_id", "нужна непустая строка")
    scenario_id = raw.get("scenario_id")
    if not isinstance(scenario_id, str) or not scenario_id.strip():
        c.fail("scenario_id", "нужна непустая строка")
    decisions = raw.get("decisions")
    if not isinstance(decisions, dict):
        c.fail("decisions", "нужен объект с supply_orders, capacity_reservations, investments, inventory_policy")
        raise PlanError(c.errors)
    for key in ("supply_orders", "capacity_reservations", "investments"):
        if not isinstance(decisions.get(key), list):
            c.fail(f"decisions.{key}", "нужен список")
    if not isinstance(decisions.get("inventory_policy"), dict):
        c.fail("decisions.inventory_policy", "нужен объект")
    if c.errors:
        raise PlanError(c.errors)

    orders = []
    seen = set()
    for i, o in enumerate(decisions["supply_orders"]):
        path = f"decisions.supply_orders[{i}]"
        if not isinstance(o, dict):
            c.fail(path, "нужен объект")
            continue
        sid, y, q = c.source(o, path), c.year(o, "year", path), c.number(o, "ordered_t", path)
        if None in (sid, y, q):
            continue
        if (sid, y) in seen:
            c.fail(path, f"заказ у {sid} на {y} год задан дважды")
        seen.add((sid, y))
        orders.append(Order(sid, y, q))

    reservations = []
    seen = set()
    for i, r in enumerate(decisions["capacity_reservations"]):
        path = f"decisions.capacity_reservations[{i}]"
        if not isinstance(r, dict):
            c.fail(path, "нужен объект")
            continue
        sid, y, q = c.source(r, path), c.year(r, "year", path), c.number(r, "reserved_capacity_t", path)
        if None in (sid, y, q):
            continue
        if (sid, y) in seen:
            c.fail(path, f"бронь у {sid} на {y} год задана дважды")
        seen.add((sid, y))
        reservations.append(Reservation(sid, y, q))

    investments = []
    seen = set()
    for i, inv in enumerate(decisions["investments"]):
        path = f"decisions.investments[{i}]"
        if not isinstance(inv, dict):
            c.fail(path, "нужен объект")
            continue
        iid = inv.get("investment_id")
        if iid not in case.investments:
            c.fail(f"{path}.investment_id", f"неизвестная инвестиция {iid}; есть {', '.join(case.investments)}")
            continue
        if iid in seen:
            c.fail(path, f"инвестиция {iid} задана дважды")
        seen.add(iid)
        if iid == "EARTH_NEW":
            oy = c.year(inv, "option_year", path)
            ey = c.year(inv, "exercise_year", path)
            if oy is not None and ey is not None and ey < oy:
                c.fail(f"{path}.exercise_year", f"исполнение {ey} раньше опциона {oy}")
            investments.append(InvestmentDecision(iid, option_year=oy, exercise_year=ey))
        elif iid == "LUNAR_ISRU":
            years = inv.get("financing_years")
            if "year" in inv and years is None:
                years = [inv["year"]]
            if not isinstance(years, list) or not years:
                c.fail(f"{path}.financing_years", "нужен непустой список годов финансирования")
                continue
            ok = []
            for j, y in enumerate(years):
                yy = c.year({f"financing_years[{j}]": y}, f"financing_years[{j}]", path)
                if yy is not None:
                    ok.append(yy)
            investments.append(InvestmentDecision(iid, financing_years=tuple(sorted(set(ok)))))
        else:
            y = c.year(inv, "year", path)
            investments.append(InvestmentDecision(iid, year=y))

    ip = decisions["inventory_policy"]
    path = "decisions.inventory_policy"
    stock = c.number(ip, "initial_stock_t", path, required=False)
    cost = c.number(ip, "initial_stock_cost_mln", path, required=False)
    src = ip.get("initial_stock_source_id")
    if src is not None and src not in case.sources:
        c.fail(f"{path}.initial_stock_source_id", f"неизвестный канал {src}")
    storage_id = ip.get("storage_id", "BASE")
    if storage_id not in case.storages:
        c.fail(f"{path}.storage_id", f"неизвестное хранилище {storage_id}; есть {', '.join(case.storages)}")
    if c.errors:
        raise PlanError(c.errors)
    inventory = InventoryPolicy(stock or 0.0, src, cost or 0.0, storage_id)
    return Plan(plan_id.strip(), scenario_id.strip(), tuple(orders), tuple(reservations), tuple(investments),
                inventory, str(raw.get("label", "")))


def load_plan(path: Path | str, case: CaseData, scenario_ids=None) -> Plan:
    p = Path(path)
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise PlanError([{"path": str(p), "message": f"файл не является JSON: {e.msg} (строка {e.lineno})"}])
    return parse_plan(raw, case, scenario_ids)


def save_plan(plan: Plan, path: Path | str) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(plan.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return p
