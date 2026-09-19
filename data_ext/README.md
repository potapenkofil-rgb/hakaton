# Копии данных с расширениями команды

Файлы организаторов в `data/` не меняются. Здесь лежат их копии с добавками,
каждая добавка помечена `TEAM_ASSUMPTION` в колонке `status`.

| Папка | Что добавлено | Зачем |
|---|---|---|
| `horizon_2041/` | год 2041 в `demand.csv` (450 т, критический 290, low 360, high 562,5: продолжение роста базы на 15 %); канал `X Source-X` в `supply_sources.csv` (60 т/год, 5,0 млн/т, бронь 0,20, take-or-pay 30 %, срок 6 мес, надёжность 0,90, доступен с 2040) | показать, что ядро считает новый период и новый источник без правок кода, а лимиты задания (CAPEX 2037/2040, резерв 45 дней, Emergency ≤ 2 года) продолжают действовать |
| `loss_2pct/` | у ZBO `loss_rate_on_throughput` 0,020 вместо 0,012 | риск R6: коэффициент потерь ZBO в кейсе синтетический (SCIENTIFIC_BASIS.md), проверяем верхнюю границу |

Запуск на копии:

```
python -m fuelhub calc results/plans/v3-earth.json --data data_ext/horizon_2041 --scenarios configs/scenarios
python -m fuelhub calc results/plans/v3-earth.json --data data_ext/loss_2pct --scenario MANDATORY_STRESS
```

Хеш данных в `meta.data_hash` у результата меняется, так что расчёт на копии
нельзя перепутать с расчётом на данных организаторов. Автоматическая проверка:
`tests/test_extension.py`, `tests/test_risks.py`.
