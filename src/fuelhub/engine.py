from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path

from . import rules
from .data import CONFIG_DIR, Assumptions, CaseData, Source, Storage
from .plan import Plan
from .scenario import Scenario

ENGINE_VERSION = "0.1"
MONTHS = 12
INF = float("inf")


def r6(x: float) -> float:
    if x == INF:
        return x
    return round(x + 0.0, 6)


@dataclass
class SourceYear:
    source: Source
    year: int
    available_months: list[int]
    reserved: float
    ordered: float
    plan_volume: float = 0.0
    actual_volume: float = 0.0
    price: float = 0.0
    payable: float = 0.0
    variable_payment: float = 0.0
    reservation_payment: float = 0.0
    capacity_limit: float = 0.0
    contract_limit: float = INF
    unavailable_reason: str = ""

    @property
    def fraction(self) -> float:
        return len(self.available_months) / MONTHS

    @property
    def monthly_actual(self) -> float:
        return self.actual_volume / len(self.available_months) if self.available_months else 0.0


@dataclass
class Availability:
    from_month: dict[str, int | None]
    reasons: dict[str, str]
    storage_switch_month: int | None
    capex: dict[int, float]
    fixed_opex: dict[int, float]
    checks: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class Engine:
    def __init__(self, case: CaseData, assumptions: Assumptions):
        self.case = case
        self.a = assumptions
        self.years = list(case.years)
        self.n_months = len(self.years) * MONTHS

    def month_index(self, year: int, month: int = 0) -> int:
        return (year - self.years[0]) * MONTHS + month

    def year_of(self, m: int) -> int:
        return self.years[m // MONTHS]

    def label(self, m: int) -> str:
        return f"{self.year_of(m)}-{m % MONTHS + 1:02d}"

    def availability(self, plan: Plan) -> Availability:
        case = self.case
        first = self.years[0]
        from_month: dict[str, int | None] = {}
        reasons: dict[str, str] = {}
        capex: dict[int, float] = {y: 0.0 for y in self.years}
        fixed: dict[int, float] = {y: 0.0 for y in self.years}
        checks: list[dict] = []
        warnings: list[str] = []

        for sid, s in case.sources.items():
            if s.available_from is not None and sid != "D":
                from_month[sid] = self.month_index(s.available_from)
                reasons[sid] = ""
            else:
                from_month[sid] = None
                reasons[sid] = "канал не введён: нет инвестиционного решения"

        en = plan.investment("EARTH_NEW")
        if en is not None:
            inv = case.investments["EARTH_NEW"]
            capex[en.option_year] += inv.option_fee
            capex[en.exercise_year] += inv.exercise_cost
            months = int(self.a["earth_new_commissioning_months"])
            m = self.month_index(en.exercise_year) + months
            if m < self.n_months:
                from_month["C"] = m
                reasons["C"] = ""
            else:
                reasons["C"] = f"ввод Earth-New через {months} мес после {en.exercise_year} выходит за горизонт"
                warnings.append(f"Earth-New: {reasons['C']}, CAPEX {inv.total_capex:.0f} оплачен без поставок")

        isru = plan.investment("LUNAR_ISRU")
        if isru is not None:
            inv = case.investments["LUNAR_ISRU"]
            src = case.sources["D"]
            share = inv.total_capex / len(isru.financing_years)
            for y in isru.financing_years:
                capex[y] += share
            deadline = src.available_from - 1
            late = [y for y in isru.financing_years if y > deadline]
            if late:
                for y in late:
                    checks.append(check_row("ISRU_FINANCING", y, "financing_year", "<=", deadline, y, "год",
                                            reason=f"ISRU должен быть профинансирован до {src.available_from}: платёж {share:.1f} в {y}",
                                            source_id="D"))
                reasons["D"] = f"финансирование ISRU завершено в {max(isru.financing_years)}, позже {deadline}"
            else:
                lead = int(self.a["isru_lead_months"])
                start = max(self.month_index(src.available_from), self.month_index(max(isru.financing_years) + 1))
                from_month["D"] = start + lead
                reasons["D"] = ""
                for y in self.years:
                    if self.month_index(y, MONTHS - 1) >= from_month["D"]:
                        fixed[y] += inv.fixed_opex

        storage_switch = None
        zbo = plan.investment("ZBO")
        if zbo is not None:
            inv = case.investments["ZBO"]
            st = case.storages["ZBO"]
            capex[zbo.year] += inv.exercise_cost
            if zbo.year < st.available_from:
                checks.append(check_row("INVESTMENT_NOT_AVAILABLE", zbo.year, "zbo_year", ">=", st.available_from, zbo.year, "год",
                                        reason=f"ZBO доступна с {st.available_from}, в плане {zbo.year}; хранилище остаётся базовым"))
            else:
                storage_switch = self.month_index(zbo.year)
                for y in self.years:
                    if y >= zbo.year:
                        fixed[y] += inv.fixed_opex

        return Availability(from_month, reasons, storage_switch, capex, fixed, checks, warnings)

    def storage_at(self, m: int, plan: Plan, av: Availability) -> Storage:
        if av.storage_switch_month is not None and m >= av.storage_switch_month:
            return self.case.storages["ZBO"]
        return self.case.storages[plan.inventory.storage_id]

    def source_years(self, plan: Plan, scenario: Scenario, av: Availability) -> tuple[list[SourceYear], list[dict]]:
        rows: list[SourceYear] = []
        checks: list[dict] = []
        basis = self.a.get("variable_payment_basis", "actual_delivery")
        for y in self.years:
            for sid, s in self.case.sources.items():
                start = av.from_month.get(sid)
                months = [m for m in range(self.month_index(y), self.month_index(y) + MONTHS) if start is not None and m >= start]
                sy = SourceYear(s, y, months, plan.reserved(sid, y), plan.ordered(sid, y))
                sy.price = scenario.price(self.case, sid, y)
                frac = sy.fraction
                sy.capacity_limit = s.capacity * frac
                if s.needs_reservation:
                    sy.contract_limit = sy.reserved * frac
                if sy.reserved > s.capacity + 1e-9:
                    checks.append(check_row("CAPACITY_EXCEEDED", y, "reserved_capacity_t", "<=", s.capacity, sy.reserved, "т",
                                            reason=f"бронь {sy.reserved:g} т у {s.name} при мощности {s.capacity:g} т/год", source_id=sid))
                if not months:
                    sy.unavailable_reason = av.reasons.get(sid) or f"{s.name} доступен с {s.available_from}"
                    if sy.ordered > 0:
                        checks.append(check_row("SOURCE_UNAVAILABLE", y, "ordered_t", "<=", 0.0, sy.ordered, "т",
                                                reason=f"заказ {sy.ordered:g} т у {s.name}: {sy.unavailable_reason}", source_id=sid))
                    if sy.reserved > 0:
                        av.warnings.append(f"{y}: бронь {sy.reserved:g} т у {s.name} не действует, канал недоступен")
                    rows.append(sy)
                    continue
                if frac < 1 and sy.ordered > 0:
                    av.warnings.append(f"{y}: {s.name} доступен {len(months)} мес из 12, заказ {sy.ordered:g} т распределён по ним")
                deliverable = min(sy.ordered, sy.capacity_limit)
                if sy.ordered > sy.capacity_limit + 1e-9:
                    checks.append(check_row("CAPACITY_EXCEEDED", y, "ordered_t", "<=", sy.capacity_limit, sy.ordered, "т",
                                            reason=f"заказ {sy.ordered:g} т у {s.name} при доступной мощности {sy.capacity_limit:g} т в {y}",
                                            source_id=sid))
                if deliverable > sy.contract_limit + 1e-9:
                    checks.append(check_row("ORDER_EXCEEDS_RESERVATION", y, "ordered_t", "<=", sy.contract_limit, deliverable, "т",
                                            reason=f"заказ {deliverable:g} т у {s.name} больше брони {sy.contract_limit:g} т", source_id=sid))
                    deliverable = sy.contract_limit
                sy.plan_volume = deliverable
                sy.actual_volume = rules.actual_delivery(deliverable, scenario.delivered_share(sid, y))
                reserved_period = sy.reserved * frac
                order_basis = sy.actual_volume if basis == "actual_delivery" else sy.plan_volume
                sy.payable = rules.payable_volume(order_basis, reserved_period, s.top_share)
                sy.variable_payment = rules.variable_payment(sy.price, sy.payable)
                sy.reservation_payment = rules.reservation_payment(s.reservation_rate, sy.reserved, frac)
                rows.append(sy)
        return rows, checks

    def run(self, plan: Plan, scenario: Scenario) -> dict:
        case = self.case
        av = self.availability(plan)
        source_rows, tech_checks = self.source_years(plan, scenario, av)
        by_month_inflow = [0.0] * self.n_months
        for sy in source_rows:
            for m in sy.available_months:
                by_month_inflow[m] += sy.monthly_actual

        demand = {y: scenario.demand(case, y) for y in self.years}
        monthly: list[dict] = []
        stock = plan.inventory.initial_stock_t
        for m in range(self.n_months):
            y = self.year_of(m)
            st = self.storage_at(m, plan, av)
            inflow = by_month_inflow[m]
            losses = rules.losses_on_throughput(inflow, st.loss_rate)
            available = stock + inflow - losses
            d_m, c_m = demand[y][0] / MONTHS, demand[y][1] / MONTHS
            served_c, served_k, shortage = rules.serve(available, d_m, c_m)
            served = served_c + served_k
            closing = rules.closing_inventory(stock, inflow, losses, served)
            monthly.append({
                "index": m, "year": y, "month": m % MONTHS + 1, "period": self.label(m),
                "storage_id": st.id, "capacity_t": st.capacity,
                "opening_t": stock, "inflow_t": inflow, "losses_t": losses,
                "demand_t": d_m, "demand_critical_t": c_m,
                "served_t": served, "served_critical_t": served_c, "shortage_t": shortage,
                "shortage_critical_t": max(0.0, c_m - served_c),
                "closing_t": closing, "overflow_t": max(0.0, closing - st.capacity),
                "holding_mln": (stock + closing) / 2 * st.holding_cost / MONTHS,
            })
            stock = closing

        yearly, inventory, checks_year = self.aggregate(plan, scenario, monthly, source_rows, demand)
        finance, totals = self.finance(plan, scenario, yearly, monthly, source_rows, av)
        checks = self.constraint_checks(scenario, yearly, finance, source_rows) + checks_year + av.checks + tech_checks
        checks.sort(key=lambda c: (c["ok"], c["year"], c["rule_id"], c.get("source_id") or ""))
        feasible = all(c["ok"] for c in checks if c["severity"] == "hard")
        first_op = {sid: self.year_of(m) for sid, m in av.from_month.items() if m is not None and m < self.n_months}
        return {
            "plan_id": plan.plan_id,
            "scenario_id": scenario.id,
            "feasible": feasible,
            "units": {"volume": "t", "money": "mln", "service_level": "share", "reserve": "days", "price": "mln/t"},
            "assumptions_reference": self.a.path,
            "yearly_balance": yearly,
            "source_schedule": [self.source_row(sy, scenario, first_op.get(sy.source.id)) for sy in source_rows],
            "inventory_trace": inventory,
            "financial_breakdown": finance,
            "totals": totals,
            "constraint_checks": checks,
            "risk_register": load_risks(),
            "warnings": av.warnings,
            "monthly_trace": [{k: (r6(v) if isinstance(v, float) else v) for k, v in row.items()} for row in monthly],
            "meta": {
                "engine_version": ENGINE_VERSION,
                "data_hash": case.data_hash,
                "data_dir": case.data_dir,
                "scenario": scenario.summary(),
                "assumptions": self.a.to_list(),
                "plan": plan.to_dict(),
            },
        }

    def aggregate(self, plan, scenario, monthly, source_rows, demand):
        yearly, inventory, checks = [], [], []
        wait_days = float(self.a["emergency_wait_days"])
        streaks = self.emergency_streaks(source_rows)
        for y in self.years:
            rows = [r for r in monthly if r["year"] == y]
            d_total, d_crit = demand[y]
            opening, closing = rows[0]["opening_t"], rows[-1]["closing_t"]
            inflow = sum(r["inflow_t"] for r in rows)
            losses = sum(r["losses_t"] for r in rows)
            served = sum(r["served_t"] for r in rows)
            served_c = sum(r["served_critical_t"] for r in rows)
            ordered = sum(sy.ordered for sy in source_rows if sy.year == y)
            planned = sum(sy.plan_volume for sy in source_rows if sy.year == y)
            reserve_req = rules.reserve_requirement(d_total)
            days = rules.stock_in_days(opening, d_total)
            equivalent_days, reserve_note = days, ""
            if days < rules.RESERVE_DAYS:
                e = next((sy for sy in source_rows if sy.year == y and sy.source.id == "E"), None)
                gap = reserve_req - opening
                e_reserved = e.reserved * e.fraction if e else 0.0
                wait_stock = rules.reserve_requirement(d_total, int(wait_days))
                if e_reserved >= gap - 1e-9 and opening >= wait_stock - 1e-9:
                    equivalent_days = float(rules.RESERVE_DAYS)
                    reserve_note = (f"запас {opening:.1f} т = {days:.0f} дн., разрыв {gap:.1f} т закрыт бронью Emergency "
                                    f"{e_reserved:.0f} т; запас покрывает {wait_days:.0f} дн. ожидания")
                elif e_reserved > 0:
                    reserve_note = (f"бронь Emergency {e_reserved:.0f} т не засчитана: "
                                    + (f"запас {opening:.1f} т меньше {wait_stock:.1f} т на {wait_days:.0f} дн. ожидания" if opening < wait_stock - 1e-9
                                       else f"разрыв {gap:.1f} т больше брони"))
            overflow = max(r["overflow_t"] for r in rows)
            if overflow > 1e-9:
                worst = max(rows, key=lambda r: r["overflow_t"])
                checks.append(check_row("STORAGE_CAPACITY", y, "physical_inventory_t", "<=", worst["capacity_t"],
                                        worst["closing_t"], "т",
                                        reason=f"запас {worst['closing_t']:.1f} т в {worst['period']} при ёмкости {worst['capacity_t']:g} т"))
            yearly.append({
                "year": y, "scenario_id": scenario.id,
                "demand_total_t": r6(d_total), "demand_critical_t": r6(d_crit),
                "opening_stock_t": r6(opening), "ordered_t": r6(ordered),
                "delivered_plan_t": r6(planned), "delivered_actual_t": r6(inflow),
                "losses_t": r6(losses), "loss_share": r6(losses / inflow) if inflow > 0 else 0.0,
                "served_total_t": r6(served), "served_critical_t": r6(served_c),
                "shortage_total_t": r6(max(0.0, d_total - served)), "shortage_critical_t": r6(max(0.0, d_crit - served_c)),
                "closing_stock_t": r6(closing),
                "service_level_total": r6(rules.service_level(served, d_total)),
                "service_level_critical": r6(rules.service_level(served_c, d_crit)),
                "reserve_required_t": r6(reserve_req), "reserve_days_at_start": r6(days),
                "reserve_equivalent_days": r6(equivalent_days),
                "reserve_note": reserve_note,
                "storage_id": rows[-1]["storage_id"], "storage_capacity_t": rows[-1]["capacity_t"],
                "max_stock_t": r6(max(r["closing_t"] for r in rows)), "overflow_t": r6(overflow),
                "emergency_base_channel": streaks[y] > 0, "emergency_streak_years": streaks[y],
            })
            inventory.append({
                "year": y, "storage_id": rows[-1]["storage_id"], "capacity_t": rows[-1]["capacity_t"],
                "opening_t": r6(opening), "inflow_t": r6(inflow), "losses_t": r6(losses),
                "outflow_t": r6(served), "closing_t": r6(closing),
                "average_stock_t": r6(sum((r["opening_t"] + r["closing_t"]) / 2 for r in rows) / len(rows)),
                "min_stock_t": r6(min(r["closing_t"] for r in rows)), "max_stock_t": r6(max(r["closing_t"] for r in rows)),
            })
        return yearly, inventory, checks

    def finance(self, plan, scenario, yearly, monthly, source_rows, av):
        rate = float(self.a["discount_rate"])
        base_year = int(self.a["discount_base_year"])
        rows, cum = [], 0.0
        for y in self.years:
            sy = [s for s in source_rows if s.year == y]
            procurement = sum(s.variable_payment for s in sy)
            reservation = sum(s.reservation_payment for s in sy)
            holding = sum(r["holding_mln"] for r in monthly if r["year"] == y)
            initial = plan.inventory.initial_stock_cost_mln if y == self.years[0] else 0.0
            capex = av.capex[y]
            cum += capex
            total = procurement + reservation + holding + av.fixed_opex[y] + capex + initial
            df = rules.discount_factor(rate, y, base_year)
            rows.append({
                "year": y, "procurement_mln": r6(procurement), "reservation_mln": r6(reservation),
                "take_or_pay_topup_mln": r6(sum((s.payable - s.actual_volume) * s.price for s in sy)),
                "holding_mln": r6(holding), "fixed_opex_mln": r6(av.fixed_opex[y]), "capex_mln": r6(capex),
                "initial_stock_mln": r6(initial), "total_mln": r6(total),
                "discount_factor": r6(df), "pv_mln": r6(total * df), "cumulative_capex_mln": r6(cum),
            })
        served = sum(r["served_total_t"] for r in yearly)
        total = sum(r["total_mln"] for r in rows)
        pv = sum(r["pv_mln"] for r in rows)
        totals = {
            "total_cost_mln": r6(total), "pv_total_mln": r6(pv), "capex_total_mln": r6(cum),
            "procurement_mln": r6(sum(r["procurement_mln"] for r in rows)),
            "reservation_mln": r6(sum(r["reservation_mln"] for r in rows)),
            "holding_mln": r6(sum(r["holding_mln"] for r in rows)),
            "fixed_opex_mln": r6(sum(r["fixed_opex_mln"] for r in rows)),
            "demand_total_t": r6(sum(r["demand_total_t"] for r in yearly)),
            "served_total_t": r6(served), "shortage_total_t": r6(sum(r["shortage_total_t"] for r in yearly)),
            "shortage_critical_t": r6(sum(r["shortage_critical_t"] for r in yearly)),
            "losses_t": r6(sum(r["losses_t"] for r in yearly)),
            "cost_per_served_t_mln": r6(total / served) if served > 0 else None,
            "pv_per_served_t_mln": r6(pv / served) if served > 0 else None,
            "min_service_level_total": r6(min(r["service_level_total"] for r in yearly)),
            "min_service_level_critical": r6(min(r["service_level_critical"] for r in yearly)),
            "discount_rate": rate, "discount_base_year": base_year,
        }
        return rows, totals

    def emergency_streaks(self, source_rows) -> dict[int, int]:
        streak, out = 0, {}
        for y in self.years:
            sy = {s.source.id: s.actual_volume for s in source_rows if s.year == y}
            e = sy.get("E", 0.0)
            others = max((v for k, v in sy.items() if k != "E"), default=0.0)
            base = e > 1e-9 and e >= others - 1e-9
            streak = streak + 1 if base else 0
            out[y] = streak
        return out

    def constraint_checks(self, scenario, yearly, finance, source_rows) -> list[dict]:
        out = []
        streaks = self.emergency_streaks(source_rows)
        by_year = {r["year"]: r for r in yearly}
        fin = {r["year"]: r for r in finance}
        for c in self.case.constraints:
            applies = c.scenario in ("ALL", scenario.id, scenario.rules_of())
            severity = c.severity if applies else "info"
            if c.metric == "critical_service_level":
                for y in self.years:
                    r = by_year[y]
                    out.append(check_row(c.id, y, c.metric, c.op, c.value, r["service_level_critical"], c.unit, severity,
                                         f"критический спрос {r['demand_critical_t']:.1f} т, выдано {r['served_critical_t']:.1f} т, не хватило {r['shortage_critical_t']:.1f} т"))
            elif c.metric == "total_service_level":
                for y in self.years:
                    r = by_year[y]
                    out.append(check_row(c.id, y, c.metric, c.op, c.value, r["service_level_total"], c.unit, severity,
                                         f"спрос {r['demand_total_t']:.1f} т, выдано {r['served_total_t']:.1f} т, не хватило {r['shortage_total_t']:.1f} т"))
            elif c.metric == "cumulative_capex":
                y = int(c.period.rsplit("_", 1)[-1])
                if y in fin:
                    out.append(check_row(c.id, y, c.metric, c.op, c.value, fin[y]["cumulative_capex_mln"], c.unit, severity,
                                         f"CAPEX нарастающим итогом к концу {y}: {fin[y]['cumulative_capex_mln']:.1f}"))
            elif c.metric == "reserve_equivalent_days":
                for y in self.years:
                    r = by_year[y]
                    note = r["reserve_note"] or f"запас на 1 января {r['opening_stock_t']:.1f} т при требуемых {r['reserve_required_t']:.1f} т"
                    out.append(check_row(c.id, y, c.metric, c.op, c.value, r["reserve_equivalent_days"], c.unit, severity, note))
            elif c.metric == "emergency_base_channel_consecutive_years":
                worst = max(self.years, key=lambda y: streaks[y])
                out.append(check_row(c.id, worst, c.metric, c.op, c.value, float(streaks[worst]), c.unit, severity,
                                     f"Emergency — основной канал {streaks[worst]} года подряд к {worst}" if streaks[worst]
                                     else "Emergency не был основным каналом"))
            elif c.metric == "losses_divided_by_throughput":
                for y in self.years:
                    limit = scenario.loss_limit(y)
                    if limit is None:
                        continue
                    r = by_year[y]
                    out.append(check_row(c.id, y, c.metric, c.op, limit, r["loss_share"], c.unit, "hard",
                                         f"потери {r['losses_t']:.1f} т от поступления {r['delivered_actual_t']:.1f} т ({r['storage_id']})"))
        return out

    def source_row(self, sy: SourceYear, scenario: Scenario, first_operating_year: int | None = None) -> dict:
        s = sy.source
        return {
            "year": sy.year, "source_id": s.id, "name": s.name,
            "available": bool(sy.available_months), "available_months": len(sy.available_months),
            "available_from": self.label(sy.available_months[0]) if sy.available_months else sy.unavailable_reason,
            "capacity_t": s.capacity, "capacity_available_t": r6(sy.capacity_limit),
            "reserved_capacity_t": r6(sy.reserved), "ordered_t": r6(sy.ordered),
            "delivered_plan_t": r6(sy.plan_volume), "delivered_actual_t": r6(sy.actual_volume),
            "delivery_share": scenario.delivered_share(s.id, sy.year),
            "payable_volume_t": r6(sy.payable), "take_or_pay_topup_t": r6(sy.payable - sy.actual_volume),
            "price_mln_per_t": r6(sy.price), "base_price_mln_per_t": s.price,
            "variable_payment_mln": r6(sy.variable_payment), "reservation_payment_mln": r6(sy.reservation_payment),
            "total_payment_mln": r6(sy.variable_payment + sy.reservation_payment),
            "lead_time": f"{s.lead_time_min:g}–{s.lead_time_max:g} {s.lead_time_unit}" if s.lead_time_min != s.lead_time_max
            else f"{s.lead_time_max:g} {s.lead_time_unit}",
            "order_by": self.order_by(sy),
            "reliability": s.reliability_for(sy.year, first_operating_year),
        }

    def order_by(self, sy: SourceYear) -> str:
        if not sy.available_months:
            return ""
        lead = sy.source.lead_time_months
        m = sy.available_months[0] - lead
        if m < 0:
            return f"до начала горизонта ({self.years[0]}), обязательство принято заранее"
        m = int(math.floor(m))
        return self.label(m)


def check_row(rule_id, year, metric, op, limit, actual, unit="", severity="hard", reason="", source_id=None) -> dict:
    ok = rules.compare(actual, op, limit)
    row = {
        "rule_id": rule_id, "year": year, "metric": metric, "operator": op,
        "limit": r6(limit), "actual": r6(actual) if actual != INF else INF,
        "excess": r6(rules.excess(actual, op, limit)) if actual != INF else 0.0,
        "unit": unit, "ok": ok, "severity": severity, "reason": reason,
    }
    if source_id:
        row["source_id"] = source_id
    return row


def load_risks(path: Path | str = CONFIG_DIR / "risks.json") -> list[dict]:
    p = Path(path)
    if not p.exists():
        return []
    raw = json.loads(p.read_text(encoding="utf-8"))
    return raw.get("risks", raw) if isinstance(raw, (dict, list)) else []


def calculate(case: CaseData, scenario: Scenario, plan: Plan, assumptions: Assumptions) -> dict:
    return Engine(case, assumptions).run(plan, scenario)
