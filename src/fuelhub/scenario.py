from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .data import CONFIG_DIR, CaseData

SCENARIO_DIR = CONFIG_DIR / "scenarios"


def _scalar(text: str):
    t = text.strip()
    if t == "" or t in ("null", "~"):
        return None
    if len(t) >= 2 and t[0] == t[-1] and t[0] in "\"'":
        return t[1:-1]
    if t in ("true", "True"):
        return True
    if t in ("false", "False"):
        return False
    try:
        return int(t)
    except ValueError:
        pass
    try:
        return float(t)
    except ValueError:
        return t


def _strip_comment(line: str) -> str:
    quote = None
    for i, ch in enumerate(line):
        if quote:
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
        elif ch == "#" and (i == 0 or line[i - 1] in " \t"):
            return line[:i]
    return line


def _lines(text: str) -> list[tuple[int, str]]:
    out = []
    for raw in text.splitlines():
        line = _strip_comment(raw).rstrip()
        if not line.strip():
            continue
        out.append((len(line) - len(line.lstrip(" ")), line.strip()))
    return out


def _parse_block(lines: list[tuple[int, str]], i: int, indent: int):
    if lines[i][1].startswith("- "):
        items = []
        while i < len(lines) and lines[i][0] == indent and lines[i][1].startswith("- "):
            items.append(_scalar(lines[i][1][2:]))
            i += 1
        return items, i
    result = {}
    while i < len(lines) and lines[i][0] == indent:
        content = lines[i][1]
        key, _, rest = content.partition(":")
        key = _scalar(key)
        rest = rest.strip()
        i += 1
        if rest:
            result[key] = _scalar(rest)
        elif i < len(lines) and lines[i][0] > indent:
            result[key], i = _parse_block(lines, i, lines[i][0])
        else:
            result[key] = None
    return result, i


def parse_yaml(text: str) -> dict:
    lines = _lines(text)
    if not lines:
        return {}
    value, i = _parse_block(lines, 0, lines[0][0])
    if i != len(lines):
        raise ValueError(f"не удалось разобрать YAML начиная со строки: {lines[i][1]}")
    return value


@dataclass(frozen=True)
class LossCeiling:
    enabled: bool = False
    from_year: int = 0
    max_share: float = 1.0


@dataclass(frozen=True)
class Scenario:
    id: str
    label: str
    status: str
    demand_profile: str
    demand_mult: dict[int, float]
    critical_mult: dict[int, float]
    price_mult: dict[str, dict[int, float]]
    delivery_share: dict[str, dict[int, float]]
    loss_ceiling: LossCeiling
    notes: tuple[str, ...] = ()
    path: str = ""
    constraint_profile: str = ""

    def rules_of(self) -> str:
        return self.constraint_profile or self.id

    def demand(self, case: CaseData, year: int) -> tuple[float, float]:
        d = case.demand[year]
        if self.demand_profile == "low":
            total, critical = d.low_total, d.low_total * d.critical_share
        elif self.demand_profile == "high":
            total, critical = d.high_total, d.high_total * d.critical_share
        else:
            total, critical = d.total, d.critical
        return total * self.demand_mult.get(year, 1.0), critical * self.critical_mult.get(year, 1.0)

    def price(self, case: CaseData, source_id: str, year: int) -> float:
        s = case.sources[source_id]
        mult = self.price_mult.get(source_id, {}).get(year, 1.0)
        return s.price * mult

    def delivered_share(self, source_id: str, year: int) -> float:
        return self.delivery_share.get(source_id, {}).get(year, 1.0)

    def loss_limit(self, year: int) -> float | None:
        c = self.loss_ceiling
        if c.enabled and year >= c.from_year:
            return c.max_share
        return None

    def summary(self) -> dict:
        return {
            "scenario_id": self.id,
            "label": self.label,
            "status": self.status,
            "demand_profile": self.demand_profile,
            "demand_multiplier": {str(k): v for k, v in self.demand_mult.items() if v != 1.0},
            "critical_demand_multiplier": {str(k): v for k, v in self.critical_mult.items() if v != 1.0},
            "variable_price_multiplier": {s: {str(k): v for k, v in m.items() if v != 1.0} for s, m in self.price_mult.items()},
            "actual_delivery_share": {s: {str(k): v for k, v in m.items()} for s, m in self.delivery_share.items()},
            "loss_ceiling": self.loss_ceiling.__dict__,
            "constraint_profile": self.rules_of(),
        }


def _year_map(raw, years) -> dict[int, float]:
    if raw is None or raw == {}:
        return {}
    if isinstance(raw, (int, float)):
        return {y: float(raw) for y in years}
    out = {}
    if "default" in raw:
        out = {y: float(raw["default"]) for y in years}
    for k, v in raw.items():
        if k != "default":
            out[int(k)] = float(v)
    return out


def _source_map(raw, case: CaseData, what: str) -> dict[str, dict[int, float]]:
    out = {}
    for name, years in (raw or {}).items():
        if name == "default":
            for sid in case.sources:
                out.setdefault(sid, {}).update(_year_map(years, case.years))
            continue
        sid = case.source_id(str(name))
        if sid is None:
            raise ValueError(f"{what}: неизвестный канал {name}")
        out.setdefault(sid, {}).update(_year_map(years, case.years))
    return out


def scenario_from_dict(raw: dict, case: CaseData, path: str = "") -> Scenario:
    if not isinstance(raw, dict) or not raw.get("scenario_id"):
        raise ValueError(f"сценарий без scenario_id: {path or raw}")
    lc = raw.get("loss_ceiling") or {}
    profile = str(raw.get("demand_profile", "base")).lower()
    if profile not in ("base", "low", "high"):
        raise ValueError(f"{raw['scenario_id']}: demand_profile должен быть base, low или high")
    return Scenario(
        id=str(raw["scenario_id"]),
        label=str(raw.get("label_ru") or raw.get("label") or raw["scenario_id"]),
        status=str(raw.get("status", "TEAM_ASSUMPTION")),
        demand_profile=profile,
        demand_mult=_year_map(raw.get("demand_multiplier"), case.years),
        critical_mult=_year_map(raw.get("critical_demand_multiplier"), case.years),
        price_mult=_source_map(raw.get("variable_price_multiplier"), case, "variable_price_multiplier"),
        delivery_share=_source_map(raw.get("actual_delivery_share"), case, "actual_delivery_share"),
        loss_ceiling=LossCeiling(bool(lc.get("enabled", False)), int(lc.get("from_year", 0) or 0),
                                 float(lc.get("max_losses_divided_by_throughput", 1.0) or 1.0)),
        notes=tuple(str(n) for n in (raw.get("notes") or [])),
        path=path,
        constraint_profile=str(raw.get("constraint_profile") or ""),
    )


def load_scenario(path: Path | str, case: CaseData) -> Scenario:
    p = Path(path)
    return scenario_from_dict(parse_yaml(p.read_text(encoding="utf-8")), case, str(p))


def load_scenarios(case: CaseData, directory: Path | str = SCENARIO_DIR) -> dict[str, Scenario]:
    out = {}
    for p in sorted(Path(directory).glob("*.yaml")):
        s = load_scenario(p, case)
        if s.id in out:
            raise ValueError(f"сценарий {s.id} задан дважды: {out[s.id].path} и {p}")
        out[s.id] = s
    return out
