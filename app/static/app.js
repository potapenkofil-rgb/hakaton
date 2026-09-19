const $ = (id) => document.getElementById(id);
const state = { inputs: null, plan: null, result: null, comparison: null, phase: "LOADING", step: 1, revision: 0, validatedRevision: -1, request: 0, source: "", rawMode: false, validation: null };

const fmt = (v, d = 1) => (v === null || v === undefined || v === "" ? "—" : typeof v === "number" ? v.toLocaleString("ru-RU", { minimumFractionDigits: d, maximumFractionDigits: d }) : v);
const pct = (v) => (typeof v === "number" ? fmt(v * 100) + " %" : "");

async function api(path, body, raw = false) {
  let res;
  try { res = await fetch(path, body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }); }
  catch { throw {message: "Нет связи с сервером. Проверьте, запущен ли сервер, и повторите действие."}; }
  if (raw) {
    if (!res.ok) {
      let error;
      try { error = await res.json(); } catch { error = {message: `Не удалось подготовить файл. Повторите попытку позже.`}; }
      throw error;
    }
    return res;
  }
  let data;
  try { data = await res.json(); } catch { throw {message: `Не удалось выполнить действие на сервере. Повторите попытку позже.`}; }
  if (!res.ok) throw data;
  return data;
}

function setStatus(text, cls) {
  const s = $("status");
  s.textContent = text;
  s.className = "status " + (cls || "");
}

function table(el, header, rows, rowClass) {
  const th = header.map((h) => `<th>${h}</th>`).join("");
  const body = rows.map((r, i) => `<tr class="${rowClass ? rowClass(r, i) : ""}">${r.map((c) => `<td class="${typeof c === "string" && c.length > 12 ? "txt" : ""}">${esc(c ?? "")}</td>`).join("")}</tr>`).join("");
  el.innerHTML = `<thead><tr>${th}</tr></thead><tbody>${body}</tbody>`;
}

function yearOptions(sel, years, value) {
  sel.innerHTML = years.map((y) => `<option value="${y}" ${y === value ? "selected" : ""}>${y}</option>`).join("");
}

function buildEditor() {
  const { years, sources } = state.inputs;
  const head = `<tr><th>Канал</th>${years.map((y) => `<th>${y}</th>`).join("")}</tr>`;
  const rows = sources.map((s) => {
    const cells = years.map((y) => `<td><span class="pair"><input data-kind="order" data-src="${s.id}" data-year="${y}" type="number" min="0" step="1" placeholder="0" title="заказ ${s.name} ${y}"><span>/</span><input data-kind="res" data-src="${s.id}" data-year="${y}" type="number" min="0" step="1" placeholder="0" title="бронь ${s.name} ${y}"></span></td>`).join("");
    return `<tr><td class="name">${s.id} ${s.name}<br><span class="hint">до ${s.capacity} т/год</span></td>${cells}</tr>`;
  }).join("");
  $("editor").innerHTML = `<thead>${head}</thead><tbody>${rows}</tbody>`;
  yearOptions($("en-option"), years, 2035);
  yearOptions($("en-exercise"), years, 2036);
  yearOptions($("zbo-year"), years, 2037);
  $("isru-years").innerHTML = years.map((y) => `<label><input type="checkbox" class="isru-year" value="${y}"> ${y}</label>`).join(" ");
  $("init-storage").innerHTML = state.inputs.storages.map(s => `<option value="${esc(s.id)}">${esc(s.id)}</option>`).join("");
  $("init-source").innerHTML = sources.map((s) => `<option value="${s.id}">${s.id} ${s.name} (${s.price} млн/т)</option>`).join("");
  $("scenario").innerHTML = state.inputs.scenarios.map((s) => `<option value="${s.scenario_id}">${esc(scenarioLabel(s.scenario_id))}</option>`).join("");
  $("editor").addEventListener("input", scheduleCalc);
  document.querySelectorAll("fieldset input, fieldset select").forEach((el) => el.addEventListener("change", scheduleCalc));
  $("scenario").addEventListener("change", scheduleCalc);
}

function renderSources() {
  const rows = state.inputs.sources.map((s) => [
    s.id + " " + s.name, s.capacity, s.price, s.reservation_rate, pct(s.top_share),
    s.lead_time_min === s.lead_time_max ? `${s.lead_time_max} ${["month","months"].includes(s.lead_time_unit) ? "мес." : ["day","days"].includes(s.lead_time_unit) ? "дн." : ["week","weeks"].includes(s.lead_time_unit) ? "нед." : s.lead_time_unit}` : `${s.lead_time_min}–${s.lead_time_max} ${["month","months"].includes(s.lead_time_unit) ? "мес." : ["day","days"].includes(s.lead_time_unit) ? "дн." : ["week","weeks"].includes(s.lead_time_unit) ? "нед." : s.lead_time_unit}`,
    s.available_from ?? "после инвестиции",
    String(s.reliability).replace(/constant:/g,"Постоянная: ").replace(/first_operating_year:/g,"Первый год: ").replace(/later:/g,"Далее: "),
    ({"long-term Earth-to-orbit channel":"Долгосрочные поставки с Земли","flexible Earth-to-orbit channel":"Гибкие поставки с Земли","capacity available only after option exercise and preparation":"Доступен после исполнения опциона и подготовки","available after required CAPEX financing and commissioning":"Доступен после полного финансирования и ввода","authoritative organizer lead time is six weeks":"Срок поставки по условиям задачи — шесть недель"})[s.notes] || s.notes,
  ]);
  table($("sources"), ["Канал", "Мощность, т/год", "Цена, млн/т", "Бронь, млн за т/год", "Мин. оплачиваемая доля", "Срок заказа", "Доступен с", "Надёжность", "Описание"], rows);
}

function readForm() {
  const orders = [], reservations = [];
  document.querySelectorAll("#editor input").forEach((el) => {
    if (el.value === "") return;
    const v = Number(el.value);
    const row = { source_id: el.dataset.src, year: Number(el.dataset.year) };
    if (el.dataset.kind === "order") orders.push({ ...row, ordered_t: v }); else reservations.push({ ...row, reserved_capacity_t: v });
  });
  const investments = [];
  if ($("en-on").checked) investments.push({ investment_id: "EARTH_NEW", option_year: Number($("en-option").value), exercise_year: Number($("en-exercise").value) });
  if ($("isru-on").checked) investments.push({ investment_id: "LUNAR_ISRU", financing_years: [...document.querySelectorAll(".isru-year:checked")].map((e) => Number(e.value)) });
  if ($("zbo-on").checked) investments.push({ investment_id: "ZBO", year: Number($("zbo-year").value) });
  return {
    plan_id: state.plan?.plan_id || `scenario-${Date.now()}`,
    label: $("plan-id").value.trim(),
    scenario_id: $("scenario").value,
    decisions: {
      supply_orders: orders,
      capacity_reservations: reservations,
      investments,
      inventory_policy: {
        initial_stock_t: Number($("init-stock").value || 0),
        initial_stock_cost_mln: Number($("init-cost").value || 0),
        initial_stock_source_id: $("init-source").value,
        storage_id: $("init-storage").value,
      },
    },
  };
}

function fillForm(plan) {
  $("plan-id").value = plan.label || plan.plan_id || "";
  if (plan.scenario_id && [...$("scenario").options].some((o) => o.value === plan.scenario_id)) $("scenario").value = plan.scenario_id;
  document.querySelectorAll("#editor input").forEach((el) => (el.value = ""));
  const d = plan.decisions || {};
  (d.supply_orders || []).forEach((o) => { const el = document.querySelector(`#editor input[data-kind=order][data-src="${CSS.escape(o.source_id)}"][data-year="${o.year}"]`); if (el) el.value = o.ordered_t; });
  (d.capacity_reservations || []).forEach((r) => { const el = document.querySelector(`#editor input[data-kind=res][data-src="${CSS.escape(r.source_id)}"][data-year="${r.year}"]`); if (el) el.value = r.reserved_capacity_t; });
  const inv = Object.fromEntries((d.investments || []).map((i) => [i.investment_id, i]));
  $("en-on").checked = !!inv.EARTH_NEW;
  if (inv.EARTH_NEW) { $("en-option").value = inv.EARTH_NEW.option_year; $("en-exercise").value = inv.EARTH_NEW.exercise_year; }
  $("isru-on").checked = !!inv.LUNAR_ISRU;
  const years = new Set(inv.LUNAR_ISRU ? (inv.LUNAR_ISRU.financing_years || [inv.LUNAR_ISRU.year]) : []);
  document.querySelectorAll(".isru-year").forEach((e) => (e.checked = years.has(Number(e.value))));
  $("zbo-on").checked = !!inv.ZBO;
  if (inv.ZBO) $("zbo-year").value = inv.ZBO.year;
  const ip = d.inventory_policy || {};
  $("init-storage").value = ip.storage_id || "BASE";
  $("init-stock").value = ip.initial_stock_t ?? "";
  $("init-cost").value = ip.initial_stock_cost_mln ?? "";
  if (ip.initial_stock_source_id) $("init-source").value = ip.initial_stock_source_id;
}

function render(res) {
  renderDashboard(res);
  const bad = res.constraint_checks.filter((c) => !c.ok);
  const hard = bad.filter((c) => c.severity === "hard");
  setStatus("Расчёт выполнен. Статус плана показан ниже.");
  renderResultSummary(res);
  $("res-scenario").textContent = scenarioLabel(res.scenario_id);
  $("viol-count").textContent = criticalText(hard.length);
  renderRiskGroups(res);
  table($("violations"), ["Ограничение", "Год", "Канал", "Фактически", "Условие", "Предел", "Отклонение", "Уровень", "Объяснение"],
    bad.map(c => [ruleName(c.rule_id), c.year, c.source_id || "", checkValue(c.actual,c), c.operator, checkValue(c.limit,c), checkValue(c.excess,c), c.severity === "hard" ? "Критическое" : c.severity === "info" ? "Информация" : "Предупреждение", c.reason]),
    r => r[7] === "Критическое" ? "bad" : r[7] === "Информация" ? "information-row" : "info");
  $("warnings").textContent = "";
  table($("balance"), ["Год", "Спрос", "в т.ч. крит.", "Запас 1 янв", "Заказано", "Поставлено", "Потери", "Выдано", "в т.ч. крит.", "Дефицит", "Остаток", "Обеспеченность спроса", "Обеспеченность крит. спроса", "Резерв, дн", "Хранилище"],
    res.yearly_balance.map((r) => [r.year, fmt(r.demand_total_t), fmt(r.demand_critical_t), fmt(r.opening_stock_t), fmt(r.ordered_t), fmt(r.delivered_actual_t), fmt(r.losses_t, 2), fmt(r.served_total_t), fmt(r.served_critical_t), fmt(r.shortage_total_t), fmt(r.closing_stock_t), pct(r.service_level_total), pct(r.service_level_critical), fmt(r.reserve_equivalent_days, 0), `${r.storage_id} ${r.storage_capacity_t} т`]),
    (r) => (parseFloat(String(r[9]).replace(",", ".")) > 0 ? "bad" : ""));
  table($("finance"), ["Год", "Закупка", "Доплата за мин. объём", "Бронь", "Хранение", "Постоянные расходы", "Инвестиции (CAPEX)", "Старт. запас", "Итого", "Приведённые затраты (PV)", "Инвестиции нарастающим итогом"],
    res.financial_breakdown.map((f) => [f.year, fmt(f.procurement_mln), fmt(f.take_or_pay_topup_mln), fmt(f.reservation_mln), fmt(f.holding_mln), fmt(f.fixed_opex_mln, 0), fmt(f.capex_mln, 0), fmt(f.initial_stock_mln), fmt(f.total_mln), fmt(f.pv_mln), fmt(f.cumulative_capex_mln, 0)]));
  const t = res.totals;
  $("totals").textContent = `Итого ${fmt(t.total_cost_mln)} млн, PV ${fmt(t.pv_total_mln)} млн, CAPEX ${fmt(t.capex_total_mln, 0)}, выдано ${fmt(t.served_total_t)} т, дефицит ${fmt(t.shortage_total_t)} т, стоимость тонны ${fmt(t.cost_per_served_t_mln, 2)} млн (ставка ${pct(t.discount_rate)}, базовый год ${t.discount_base_year})`;
  const sched = res.source_schedule.filter((s) => s.ordered_t || s.reserved_capacity_t);
  table($("schedule"), ["Год", "Канал", "Доступен с", "Бронь", "Заказ", "План", "Факт", "Оплач. объём", "Цена", "Закупка", "За бронь", "Заказать до"],
    sched.map((s) => [s.year, `${s.source_id} ${s.name}`, s.available_from, fmt(s.reserved_capacity_t, 0), fmt(s.ordered_t, 0), fmt(s.delivered_plan_t), fmt(s.delivered_actual_t), fmt(s.payable_volume_t), fmt(s.price_mln_per_t, 2), fmt(s.variable_payment_mln), fmt(s.reservation_payment_mln), s.order_by]),
    (r) => (r[6] !== r[5] ? "info" : ""));
}

function renderPlanList(plans, selected) {
  $("plan-list").innerHTML = plans.map((p) => `<option value="${esc(p.file.replace(/\.json$/, ""))}" ${p.plan_id === selected ? "selected" : ""}>${esc(p.label || p.plan_id)} · ${esc(p.plan_id)}</option>`).join("");
}

