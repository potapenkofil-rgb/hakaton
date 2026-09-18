import pytest

from fuelhub import SCENARIO_DIR, parse_yaml, scenario_from_dict
from fuelhub.scenario import load_scenario


def test_organizer_files_parse(case, scenarios):
    assert set(scenarios) == {"BASE", "MANDATORY_STRESS"}
    assert scenarios["BASE"].status == "CASE_INPUT"
    assert scenarios["MANDATORY_STRESS"].label == "Обязательный стрессовый сценарий"


def test_stress_multipliers_exact(case, scenarios):
    s = scenarios["MANDATORY_STRESS"]
    assert {y: s.demand_mult.get(y, 1.0) for y in case.years} == {2035: 1, 2036: 1, 2037: 1, 2038: 1.15, 2039: 1.15, 2040: 1.15}
    assert s.price_mult["A"][2038] == 1.25 and s.price_mult["A"][2040] == 1.0
    assert s.price_mult["B"][2039] == 1.25
    assert "C" not in s.price_mult and "D" not in s.price_mult and "E" not in s.price_mult
    assert s.delivery_share["D"] == {2038: 0.55, 2039: 0.75, 2040: 1.0}
    assert s.loss_ceiling.enabled and s.loss_ceiling.from_year == 2038 and s.loss_ceiling.max_share == 0.02
    assert s.loss_limit(2037) is None and s.loss_limit(2038) == 0.02


def test_base_is_identity(case, scenarios):
    s = scenarios["BASE"]
    for y in case.years:
        assert s.demand(case, y) == (case.demand[y].total, case.demand[y].critical)
        for sid in case.sources:
            assert s.price(case, sid, y) == case.sources[sid].price
            assert s.delivered_share(sid, y) == 1.0
        assert s.loss_limit(y) is None


def test_parser_basics():
    text = """
# комментарий
a: 1
b: 2.5
c: "строка # не комментарий"
d: yes_text
e: true
f: null
nested:
  2038: 1.15
  Earth-Core:
    2039: 1.25
list:
  - one
  - "two"
"""
    got = parse_yaml(text)
    assert got == {"a": 1, "b": 2.5, "c": "строка # не комментарий", "d": "yes_text", "e": True, "f": None,
                   "nested": {2038: 1.15, "Earth-Core": {2039: 1.25}}, "list": ["one", "two"]}


def test_parser_empty_and_bad():
    assert parse_yaml("") == {}
    with pytest.raises(ValueError):
        parse_yaml("a:\n  b: 1\n c: 2\n")


def test_scenario_without_id_rejected(case):
    with pytest.raises(ValueError):
        scenario_from_dict({"label_ru": "без id", "demand_multiplier": {"2035": 1.1}}, case)


def test_scenario_unknown_source_rejected(case):
    with pytest.raises(ValueError):
        scenario_from_dict({"scenario_id": "T", "variable_price_multiplier": {"Mars": {2035: 2}}}, case)


def test_scenario_bad_profile_rejected(case):
    with pytest.raises(ValueError):
        scenario_from_dict({"scenario_id": "T", "demand_profile": "medium"}, case)


def test_low_high_profiles_keep_critical_share(case):
    low = scenario_from_dict({"scenario_id": "L", "demand_profile": "low"}, case)
    high = scenario_from_dict({"scenario_id": "H", "demand_profile": "high"}, case)
    for y in case.years:
        d = case.demand[y]
        assert low.demand(case, y) == pytest.approx((d.low_total, d.low_total * d.critical / d.total))
        assert high.demand(case, y) == pytest.approx((d.high_total, d.high_total * d.critical / d.total))
    assert high.demand(case, 2040)[0] == 487.5


def test_source_ids_accepted_as_well_as_names(case):
    s = scenario_from_dict({"scenario_id": "T", "variable_price_multiplier": {"A": {2036: 2.0}, "Earth-Flex": {2036: 3.0}}}, case)
    assert s.price(case, "A", 2036) == pytest.approx(12.4)
    assert s.price(case, "B", 2036) == pytest.approx(26.7)
    assert s.price(case, "A", 2035) == 6.2


def test_default_key_applies_to_all(case):
    s = scenario_from_dict({"scenario_id": "T", "demand_multiplier": {"default": 1.1, 2040: 1.3},
                            "variable_price_multiplier": {"default": {"default": 1.5}}}, case)
    assert s.demand(case, 2035)[0] == pytest.approx(110)
    assert s.demand(case, 2040)[0] == pytest.approx(390 * 1.3)
    for sid in case.sources:
        assert s.price(case, sid, 2037) == pytest.approx(case.sources[sid].price * 1.5)


def test_summary_is_json_friendly(scenarios):
    import json
    json.dumps(scenarios["MANDATORY_STRESS"].summary())


def test_duplicate_scenario_id_rejected(case, tmp_path):
    from fuelhub import load_scenarios
    (tmp_path / "a.yaml").write_text("scenario_id: X\n", encoding="utf-8")
    (tmp_path / "b.yaml").write_text("scenario_id: X\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_scenarios(case, tmp_path)


def test_load_scenario_file(case):
    s = load_scenario(SCENARIO_DIR / "mandatory_stress.yaml", case)
    assert s.id == "MANDATORY_STRESS"
