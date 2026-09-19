import pytest

from fuelhub import rules


def test_serve_critical_first():
    assert rules.serve(50, 100, 60) == (50, 0, 50)
    assert rules.serve(70, 100, 60) == (60, 10, 30)
    assert rules.serve(120, 100, 60) == (60, 40, 0)


def test_serve_never_negative():
    assert rules.serve(-5, 10, 5) == (0, 0, 10)
    assert rules.serve(0, 0, 0) == (0, 0, 0)


def test_serve_critical_capped_by_demand():
    assert rules.serve(100, 10, 30) == (10, 0, 0)


def test_service_level_zero_demand_defined():
    assert rules.service_level(0, 0) == 1.0
    assert rules.service_level(5, 10) == 0.5


def test_payable_volume_edges():
    assert rules.payable_volume(0, 100, 0.7) == 70
    assert rules.payable_volume(80, 100, 0.7) == 80
    assert rules.payable_volume(0, 0, 0.7) == 0
    assert rules.payable_volume(10, 100, 0) == 10


def test_reservation_payment_full_year_default():
    assert rules.reservation_payment(0.45, 190) == pytest.approx(85.5)


def test_reserve_requirement_case_years():
    assert rules.reserve_requirement(390) == pytest.approx(48.08, abs=0.01)
    assert rules.reserve_requirement(448.5) == pytest.approx(55.29, abs=0.01)
    assert rules.reserve_requirement(100, 42) == pytest.approx(11.51, abs=0.01)


def test_stock_in_days():
    assert rules.stock_in_days(45, 365) == 45
    assert rules.stock_in_days(0, 100) == 0
    assert rules.stock_in_days(10, 0) == rules.MAX_DAYS


def test_capacity_excess():
    assert rules.capacity_excess(12, 10) == 2
    assert rules.capacity_excess(10, 10) == 0
    assert rules.capacity_excess(8, 10) == 0


def test_discount_factor():
    assert rules.discount_factor(0.08, 2035, 2035) == 1
    assert rules.discount_factor(0.08, 2036, 2035) == pytest.approx(1 / 1.08)
    assert rules.discount_factor(0.0, 2040, 2035) == 1


@pytest.mark.parametrize("actual,op,limit,ok,exc", [
    (0.99, ">=", 0.99, True, 0), (0.98, ">=", 0.99, False, 0.01), (1800, "<=", 1800, True, 0), (1801, "<=", 1800, False, 1),
    (3, "<=", 2, False, 1), (45, ">=", 45, True, 0), (44.9, ">=", 45, False, 0.1),
])
def test_compare_and_excess(actual, op, limit, ok, exc):
    assert rules.compare(actual, op, limit) is ok
    assert rules.excess(actual, op, limit) == pytest.approx(exc)


def test_compare_unknown_operator():
    with pytest.raises(ValueError):
        rules.compare(1, "~", 1)
