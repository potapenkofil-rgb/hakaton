# Модель данных ядра: что на входе, что на выходе

Единственный источник чисел — `src/fuelhub`. Интерфейс отправляет план и
получает результат; формул в интерфейсе нет. Все объёмы в тоннах, деньги в
млн условных единиц, обслуживание — доля 0…1, резерв — в днях и тоннах.

```
 data/*.csv  ──┐
               ├──► CaseData  ──┐
 scenarios/*  ─┘                ├──► calculate(case, scenario, plan) ──► Result ──► экран
                                │                                                 └──► CSV / XLSX
 план из UI  ───────────────────┘
```

## Вход 1. Данные кейса (`data/*.csv`, только чтение)

| Объект | Поля | Откуда |
|---|---|---|
| `demand[year]` | `total`, `critical`, `low_total`, `high_total` | `demand.csv` |
| `sources[id]` | `name`, `capacity_t`, `price_mln_per_t`, `reservation_rate`, `top_share`, `lead_time` (min, max, unit), `reliability[year]`, `available_from` | `supply_sources.csv` |
| `storages[id]` | `capacity_t`, `loss_rate`, `holding_cost`, `capex`, `fixed_opex`, `available_from` | `storage_options.csv` |
| `investments[id]` | `option_fee`, `exercise_cost`, `total_capex`, `fixed_opex`, правило ввода | `investment_options.csv` |
| `constraints[]` | `id`, `metric`, `op`, `value`, `unit`, `period`, `scenario`, `severity` | `constraints.csv` |

## Вход 2. Сценарий (`configs/scenarios/*.yaml`)

```yaml
scenario_id: MANDATORY_STRESS
demand_profile: base                 # base | low | high  (только в сценариях команды)
demand_multiplier:          {2038: 1.15, 2039: 1.15, 2040: 1.15}
critical_demand_multiplier: {2038: 1.15, 2039: 1.15, 2040: 1.15}
variable_price_multiplier:  {Earth-Core: {2038: 1.25, 2039: 1.25}, Earth-Flex: {2038: 1.25, 2039: 1.25}}
actual_delivery_share:      {Lunar-ISRU: {2038: 0.55, 2039: 0.75, 2040: 1.0}}
loss_ceiling:               {enabled: true, from_year: 2038, max_losses_divided_by_throughput: 0.02}
```

Чего нет в файле — то 1.0 / выключено. `BASE` — пустой сценарий.
Свои сценарии называются `TEAM_*` и лежат отдельными файлами.

## Вход 3. План оператора (то, что шлёт интерфейс)

```json
{
  "plan_id": "base-v1",
  "scenario_id": "BASE",
  "decisions": {
    "supply_orders": [
      {"source_id": "A", "year": 2035, "ordered_t": 90},
      {"source_id": "B", "year": 2035, "ordered_t": 20}
    ],
    "capacity_reservations": [
      {"source_id": "A", "year": 2035, "reserved_capacity_t": 100},
      {"source_id": "B", "year": 2035, "reserved_capacity_t": 30}
    ],
    "investments": [
      {"investment_id": "EARTH_NEW",  "option_year": 2035, "exercise_year": 2036},
      {"investment_id": "LUNAR_ISRU", "financing_years": [2036, 2037]},
      {"investment_id": "ZBO",        "year": 2037}
    ],
    "inventory_policy": {
      "initial_stock_t": 15,
      "initial_stock_source_id": "B",
      "initial_stock_cost_mln": 133.5,
      "storage_id": "BASE"
    }
  }
}
```

- `supply_orders` — сколько тонн хотим получить от канала в году. Год — год
  поставки; ядро само проверяет, что заказ можно было разместить за lead time.
- `capacity_reservations` — сколько мощности бронируем у канала на год.
  Поставка не может превышать бронь; за бронь платится ставка × объём;
  take-or-pay считается от брони.
- `investments` — решения по стройкам. `EARTH_NEW`: год оплаты опциона (90)
  и год исполнения (270), мощность появляется через 24 месяца после
  исполнения. `LUNAR_ISRU`: годы, по которым равными долями раскладываются
  1250, все до 2038. `ZBO`: год оплаты 180, с этого же года хранилище 120 т
  и потери 1,2 %.
- `inventory_policy` — стартовый запас на 1 января 2035: сколько, из какого
  канала и за сколько (это CAPEX-подобный платёж 2035 года), и какое
  хранилище на старте.

Лишние поля не ломают план (`additionalProperties: true` у организаторов),
но ядро их не читает. `scenario_id` в плане — сценарий по умолчанию; при
расчёте его можно переопределить (`--scenario` в CLI, поле запроса в API).
Для `LUNAR_ISRU` вместо `financing_years` можно написать `"year": 2037`.

## Выход. Результат расчёта

```json
{
  "plan_id": "base-v1",
  "scenario_id": "BASE",
  "feasible": false,
  "units": {"volume": "t", "money": "mln", "service_level": "share", "reserve": "days"},
  "assumptions_reference": "configs/assumptions.json",

  "yearly_balance": [
    {"year": 2035, "demand_total_t": 100, "demand_critical_t": 80,
     "opening_stock_t": 15, "ordered_t": 110, "delivered_plan_t": 110, "delivered_actual_t": 110,
     "losses_t": 4.95, "served_total_t": 100, "served_critical_t": 80,
     "shortage_total_t": 0, "shortage_critical_t": 0, "closing_stock_t": 20.05,
     "service_level_total": 1.0, "service_level_critical": 1.0,
     "reserve_required_t": 12.33, "reserve_days_at_start": 54.8,
     "storage_capacity_t": 70, "loss_share": 0.045}
  ],

  "source_schedule": [
    {"year": 2035, "source_id": "A", "name": "Earth-Core", "available": true,
     "reserved_capacity_t": 100, "ordered_t": 90, "delivered_plan_t": 90, "delivered_actual_t": 90,
     "payable_volume_t": 90, "take_or_pay_topup_t": 0, "price_mln_per_t": 6.2,
     "variable_payment_mln": 558, "reservation_payment_mln": 45, "base_channel": true}
  ],

  "inventory_trace": [
    {"year": 2035, "opening_t": 15, "inflow_t": 110, "losses_t": 4.95, "outflow_t": 100,
     "closing_t": 20.05, "average_stock_t": 17.5, "capacity_t": 70, "storage_id": "BASE"}
  ],

  "financial_breakdown": [
    {"year": 2035, "procurement_mln": 736, "reservation_mln": 49.5, "holding_mln": 12.6,
     "fixed_opex_mln": 0, "capex_mln": 133.5, "total_mln": 931.6,
     "discount_factor": 1.0, "pv_mln": 931.6, "cumulative_capex_mln": 133.5}
  ],

  "totals": {
    "total_cost_mln": 0, "pv_total_mln": 0, "capex_total_mln": 0,
    "served_total_t": 0, "shortage_total_t": 0, "cost_per_served_t_mln": 0,
    "min_service_level_total": 0, "min_service_level_critical": 0
  },

  "constraint_checks": [
    {"rule_id": "BASE_TOTAL_SERVICE", "year": 2039, "metric": "total_service_level",
     "operator": ">=", "limit": 0.97, "actual": 0.9375, "excess": 0.0325,
     "ok": false, "severity": "hard", "reason": "спрос 320 т, выдано 300 т, не хватило 20 т"},
    {"rule_id": "CAPACITY_EXCEEDED", "year": 2036, "source_id": "B", "metric": "delivered_t",
     "operator": "<=", "limit": 110, "actual": 112, "excess": 2, "ok": false, "severity": "hard",
     "reason": "заказ 112 т у Earth-Flex при мощности 110 т"}
  ],

  "risk_register": [],
  "warnings": ["Emergency базовый канал в 2036: год 1 из допустимых 2"]
}
```

- `feasible` — `false`, если есть хоть одна непройденная проверка с
  `severity: hard`. Такой план интерфейс показывает как неисполнимый.
  Требования BASE к сервису в других сценариях идут со `severity: info`:
  видны, но план не «ломают».
- `yearly_balance` — главная таблица экрана оператора, строка на год. Кроме
  показанного выше есть `loss_share`, `reserve_note` (почему резерв
  засчитан или нет), `storage_id`, `max_stock_t`, `overflow_t`,
  `emergency_base_channel`, `emergency_streak_years`.
- `source_schedule` — строка на каждую пару год × канал, отсюда контрактная
  картина и платежи. Дополнительно: `available_months`, `available_from`
  (месяц `2038-03` или причина недоступности), `capacity_available_t`,
  `delivery_share`, `lead_time`, `order_by` (когда заказ должен быть
  размещён), `reliability` (для реестра рисков, на поставку не влияет).
- `inventory_trace` — движение бака по годам, отсюда график запаса;
  `monthly_trace` — то же по месяцам (72 строки), для графика и
  проверки переполнения.
- `financial_breakdown` — деньги по годам, отсюда бюджет; есть ещё
  `take_or_pay_topup_mln` и `initial_stock_mln`. `totals` — итоги за
  горизонт: `total_cost_mln`, `pv_total_mln`, `capex_total_mln`,
  `served_total_t`, `shortage_total_t`, `cost_per_served_t_mln`,
  `min_service_level_total/critical` и составляющие расходов.
- `constraint_checks` — все проверки, и пройденные тоже (`ok: true`); у
  нарушений всегда год, факт, порог, превышение и причина словами.
  Правила из `data/constraints.csv`: `BASE_CRITICAL_SERVICE`,
  `BASE_TOTAL_SERVICE`, `CAPEX_2037`, `CAPEX_2040`, `RESERVE_45D`,
  `EMERGENCY_BASE_STREAK`, `STRESS_LOSS_LIMIT` (только где сценарий задаёт
  потолок потерь). Технические, только при нарушении:
  `CAPACITY_EXCEEDED` (бронь или заказ больше мощности),
  `ORDER_EXCEEDS_RESERVATION`, `SOURCE_UNAVAILABLE`, `STORAGE_CAPACITY`,
  `ISRU_FINANCING`, `INVESTMENT_NOT_AVAILABLE`. Список отсортирован:
  нарушения первыми.
- `risk_register` — заполняется аналитиками из `configs/risks.json`, ядро
  прикладывает как есть.
- `warnings` — заметки, не нарушения (канал доступен часть года, бронь у
  недоступного канала, ввод за горизонтом).
- `meta` — версия ядра, хэш данных, сценарий, допущения и сам план: по
  результату можно восстановить, из чего он посчитан.

Выгрузка CSV — те же таблицы, развёрнутые в длинный формат
`scenario_id, plan_id, year, entity, metric, value, unit`; XLSX — по листу
на таблицу.

## Ошибки ввода

Если план не проходит валидацию, расчёта нет, возвращается:

```json
{
  "error": "INVALID_PLAN",
  "details": [
    {"path": "decisions.capacity_reservations[0].reserved_capacity_t",
     "message": "отрицательный объём: -1"},
    {"path": "decisions.supply_orders[3].source_id",
     "message": "неизвестный канал Source-X; есть A, B, C, D, E"}
  ]
}
```

Что валидируется до расчёта: id канала/инвестиции/хранилища существуют,
год внутри горизонта, объёмы не отрицательные, `scenario_id` известен,
план — объект нужной формы. Превышение мощности, брони, ёмкости, CAPEX —
это не ошибка ввода, а нарушение: план считается и попадает в
`constraint_checks`.

## API для интерфейса

| Метод | Что делает |
|---|---|
| `GET /api/inputs` | данные кейса, список сценариев, список сохранённых планов |
| `POST /api/calculate` | `{plan, scenario_id, overrides?}` → результат |
| `POST /api/compare` | `{plan, scenarios?, overrides?}` → результаты по сценариям и разница по годам |
| `POST /api/plans` / `GET /api/plans/{id}` | сохранить / открыть план (`results/plans/*.json`) |
| `POST /api/export?format=csv\|xlsx\|json&scenario=…` | `{plan, overrides?}` → файл |
| `GET /api/export/{plan_id}?format=csv\|xlsx` | выгрузка сохранённого плана |

### Правки данных (`overrides`)

Интерфейс может изменить числа кейса, не трогая файлы организаторов. Поле
`overrides` в запросе:

```json
{
  "sources":  {"A": {"price": 7.0, "capacity": 200, "reservation_rate": 0.5, "top_share": 0.7}},
  "storages": {"ZBO": {"capacity": 150, "loss_rate": 0.02, "holding_cost": 0.6, "capex": 200, "fixed_opex": 15}},
  "demand":   {"2040": {"total": 420, "critical": 260}}
}
```

Разрешены только эти поля, значения — числа не меньше нуля; неизвестный
элемент или поле дают `INVALID_PLAN` с путём вида `overrides.sources.A.price`.
Значения, равные исходным, отбрасываются. Результат несёт правки в
`meta.overrides`, а `meta.data_hash` получает суффикс `+<хэш правок>`, так что
расчёт на изменённых данных не спутать с расчётом на данных организаторов.
В длинной выгрузке правки идут строками `override:sources:A / price`, в XLSX
на листе `summary` строками `override:sources.A.price`.

То же самое из командной строки: `python -m fuelhub calc plan.json --scenario BASE`,
`python -m fuelhub export plan.json --format csv`,
`python -m fuelhub --overrides правки.json calc plan.json`.
