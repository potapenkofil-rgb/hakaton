from __future__ import annotations

DAYS_PER_YEAR = 365
RESERVE_DAYS = 45


def closing_inventory(opening: float, delivered: float, losses: float, served: float) -> float:
    return opening + delivered - losses - served


def losses_on_throughput(gross_inflow: float, loss_rate: float) -> float:
    return gross_inflow * loss_rate


def serve(available: float, demand: float, critical: float) -> tuple[float, float, float]:
    critical = min(critical, demand)
    served_critical = min(critical, max(available, 0.0))
    served_commercial = min(demand - critical, max(available - served_critical, 0.0))
    served = served_critical + served_commercial
    return served_critical, served_commercial, max(0.0, demand - served)


def service_level(served: float, demand: float) -> float:
    if demand <= 0:
        return 1.0
    return served / demand


def payable_volume(ordered: float, reserved: float, take_or_pay_share: float) -> float:
    return max(ordered, take_or_pay_share * reserved)


def variable_payment(price: float, payable: float) -> float:
    return price * payable


def reservation_payment(rate: float, reserved: float, period_fraction: float = 1.0) -> float:
    return rate * reserved * period_fraction


def reserve_requirement(annual_demand: float, days: int = RESERVE_DAYS) -> float:
    return annual_demand * days / DAYS_PER_YEAR


MAX_DAYS = 9999.0


def stock_in_days(stock: float, annual_demand: float) -> float:
    if annual_demand <= 0:
        return MAX_DAYS
    return min(MAX_DAYS, stock / annual_demand * DAYS_PER_YEAR)


def capacity_excess(requested: float, capacity: float) -> float:
    return max(0.0, requested - capacity)


def actual_delivery(planned: float, delivery_share: float) -> float:
    return planned * delivery_share


def discount_factor(rate: float, year: int, base_year: int) -> float:
    return 1.0 / (1.0 + rate) ** (year - base_year)


def compare(actual: float, op: str, limit: float, tol: float = 1e-9) -> bool:
    if op == ">=":
        return actual >= limit - tol
    if op == "<=":
        return actual <= limit + tol
    if op == ">":
        return actual > limit + tol
    if op == "<":
        return actual < limit - tol
    if op == "==":
        return abs(actual - limit) <= tol
    raise ValueError(f"неизвестный оператор {op}")


def excess(actual: float, op: str, limit: float) -> float:
    if op in (">=", ">"):
        return max(0.0, limit - actual)
    if op in ("<=", "<"):
        return max(0.0, actual - limit)
    return abs(actual - limit)
