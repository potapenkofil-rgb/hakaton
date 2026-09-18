const $ = (id) => document.getElementById(id);
const state = { inputs: null, result: null, timer: null };

const fmt = (v, d = 1) => (v === null || v === undefined || v === "" ? "" : typeof v === "number" ? v.toLocaleString("ru-RU", { minimumFractionDigits: d, maximumFractionDigits: d }) : v);
const pct = (v) => (typeof v === "number" ? (v * 100).toFixed(1) + " %" : "");

async function api(path, body, raw = false) {
  const res = await fetch(path, body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (raw) {
    if (!res.ok) throw await res.json();
    return res;
  }
  const data = await res.json();
  if (!res.ok) throw data;
  return data;
}

function showError(err) {
  const box = $("error");
  if (!err) { box.classList.add("hidden"); box.textContent = ""; return; }
  let text = err.error === "INVALID_PLAN"
    ? "План не принят:\n" + err.details.map((d) => `• ${d.path}: ${d.message}`).join("\n")
    : (err.message || err.error || String(err));
  box.textContent = text + "\n\nИсправь поле, о котором написано выше, или нажми «Сброс» — вернётся план base-v1.";
  box.classList.remove("hidden");
  setStatus("Ошибка ввода — расчёта нет. Что не так — написано в красном поле ниже; кнопка «Сброс» вернёт base-v1", "bad");
  box.scrollIntoView({ behavior: "smooth", block: "center" });
}

async function reset() {
  $("plan-list").value = "base-v1";
  await open();
}

function setStatus(text, cls) {
  const s = $("status");
  s.textContent = text;
  s.className = "status " + (cls || "");
}

function table(el, header, rows, rowClass) {
  const th = header.map((h) => `<th>${h}</th>`).join("");
  const body = rows.map((r, i) => `<tr class="${rowClass ? rowClass(r, i) : ""}">${r.map((c) => `<td class="${typeof c === "string" && c.length > 12 ? "txt" : ""}">${c ?? ""}</td>`).join("")}</tr>`).join("");
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
  $("init-source").innerHTML = sources.map((s) => `<option value="${s.id}">${s.id} ${s.name} (${s.price} млн/т)</option>`).join("");
  $("scenario").innerHTML = state.inputs.scenarios.map((s) => `<option value="${s.scenario_id}">${s.scenario_id} — ${s.label}</option>`).join("");
  $("editor").addEventListener("input", scheduleCalc);
  document.querySelectorAll("fieldset input, fieldset select").forEach((el) => el.addEventListener("change", scheduleCalc));
  $("scenario").addEventListener("change", calc);
}

function renderSources() {
  const rows = state.inputs.sources.map((s) => [
    s.id + " " + s.name, s.capacity, s.price, s.reservation_rate, pct(s.top_share),
    s.lead_time_min === s.lead_time_max ? `${s.lead_time_max} ${s.lead_time_unit}` : `${s.lead_time_min}–${s.lead_time_max} ${s.lead_time_unit}`,
    s.available_from ?? "после инвестиции", s.reliability, s.notes,
  ]);
  table($("sources"), ["Канал", "Мощность, т/год", "Цена, млн/т", "Бронь, млн за т/год", "Take-or-pay", "Срок заказа", "Доступен с", "Надёжность", ""], rows);
}

function readPlan() {
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
    plan_id: $("plan-id").value,
    scenario_id: $("scenario").value,
    decisions: {
      supply_orders: orders,
      capacity_reservations: reservations,
      investments,
      inventory_policy: {
        initial_stock_t: Number($("init-stock").value || 0),
        initial_stock_cost_mln: Number($("init-cost").value || 0),
        initial_stock_source_id: $("init-source").value,
        storage_id: "BASE",
      },
    },
  };
}

function fillForm(plan) {
  $("plan-id").value = plan.plan_id || "";
  if (plan.scenario_id && [...$("scenario").options].some((o) => o.value === plan.scenario_id)) $("scenario").value = plan.scenario_id;
  document.querySelectorAll("#editor input").forEach((el) => (el.value = ""));
  const d = plan.decisions || {};
  (d.supply_orders || []).forEach((o) => { const el = document.querySelector(`#editor input[data-kind=order][data-src="${o.source_id}"][data-year="${o.year}"]`); if (el) el.value = o.ordered_t; });
  (d.capacity_reservations || []).forEach((r) => { const el = document.querySelector(`#editor input[data-kind=res][data-src="${r.source_id}"][data-year="${r.year}"]`); if (el) el.value = r.reserved_capacity_t; });
  const inv = Object.fromEntries((d.investments || []).map((i) => [i.investment_id, i]));
  $("en-on").checked = !!inv.EARTH_NEW;
  if (inv.EARTH_NEW) { $("en-option").value = inv.EARTH_NEW.option_year; $("en-exercise").value = inv.EARTH_NEW.exercise_year; }
  $("isru-on").checked = !!inv.LUNAR_ISRU;
  const years = new Set(inv.LUNAR_ISRU ? (inv.LUNAR_ISRU.financing_years || [inv.LUNAR_ISRU.year]) : []);
  document.querySelectorAll(".isru-year").forEach((e) => (e.checked = years.has(Number(e.value))));
  $("zbo-on").checked = !!inv.ZBO;
  if (inv.ZBO) $("zbo-year").value = inv.ZBO.year;
  const ip = d.inventory_policy || {};
  $("init-stock").value = ip.initial_stock_t ?? 0;
  $("init-cost").value = ip.initial_stock_cost_mln ?? 0;
  if (ip.initial_stock_source_id) $("init-source").value = ip.initial_stock_source_id;
}

function scheduleCalc() {
  clearTimeout(state.timer);
  state.timer = setTimeout(calc, 500);
}

async function calc() {
  setStatus("Считаю…", "wait");
  try {
    const res = await api("/api/calculate", { plan: readPlan(), scenario_id: $("scenario").value });
    showError(null);
    state.result = res;
    render(res);
  } catch (e) { showError(e); }
}

function render(res) {
  const bad = res.constraint_checks.filter((c) => !c.ok);
  const hard = bad.filter((c) => c.severity === "hard");
  setStatus(res.feasible ? `План ${res.plan_id} в сценарии ${res.scenario_id}: исполним, нарушений нет` : `План ${res.plan_id} в сценарии ${res.scenario_id}: НЕ исполним — ${hard.length} нарушений`, res.feasible ? "ok" : "bad");
  $("res-scenario").textContent = res.scenario_id;
  $("viol-count").textContent = bad.length ? `${hard.length} жёстких, ${bad.length - hard.length} справочных` : "нет";
  table($("violations"), ["Правило", "Год", "Канал", "Факт", "", "Порог", "Превышение", "Уровень", "Причина"],
    bad.map((c) => [c.rule_id, c.year, c.source_id || "", fmt(c.actual, 3), c.operator, fmt(c.limit, 3), fmt(c.excess, 3), c.severity, c.reason]),
    (r) => (r[7] === "hard" ? "bad" : "info"));
  $("warnings").textContent = (res.warnings || []).join(" · ");
  table($("balance"), ["Год", "Спрос", "в т.ч. крит.", "Запас 1 янв", "Заказано", "Приехало", "Потери", "Выдано", "в т.ч. крит.", "Дефицит", "Остаток", "SL общ", "SL крит", "Резерв, дн", "Бак"],
    res.yearly_balance.map((r) => [r.year, fmt(r.demand_total_t), fmt(r.demand_critical_t), fmt(r.opening_stock_t), fmt(r.ordered_t), fmt(r.delivered_actual_t), fmt(r.losses_t, 2), fmt(r.served_total_t), fmt(r.served_critical_t), fmt(r.shortage_total_t), fmt(r.closing_stock_t), pct(r.service_level_total), pct(r.service_level_critical), fmt(r.reserve_equivalent_days, 0), `${r.storage_id} ${r.storage_capacity_t} т`]),
    (r) => (parseFloat(String(r[9]).replace(",", ".")) > 0 ? "bad" : ""));
  table($("finance"), ["Год", "Закупка", "в т.ч. take-or-pay", "Бронь", "Хранение", "Фикс. OPEX", "CAPEX", "Старт. запас", "Итого", "PV", "CAPEX накоп."],
    res.financial_breakdown.map((f) => [f.year, fmt(f.procurement_mln), fmt(f.take_or_pay_topup_mln), fmt(f.reservation_mln), fmt(f.holding_mln), fmt(f.fixed_opex_mln, 0), fmt(f.capex_mln, 0), fmt(f.initial_stock_mln), fmt(f.total_mln), fmt(f.pv_mln), fmt(f.cumulative_capex_mln, 0)]));
  const t = res.totals;
  $("totals").textContent = `Итого ${fmt(t.total_cost_mln)} млн, PV ${fmt(t.pv_total_mln)} млн, CAPEX ${fmt(t.capex_total_mln, 0)}, выдано ${fmt(t.served_total_t)} т, дефицит ${fmt(t.shortage_total_t)} т, стоимость тонны ${fmt(t.cost_per_served_t_mln, 2)} млн (r = ${t.discount_rate}, база ${t.discount_base_year})`;
  const sched = res.source_schedule.filter((s) => s.ordered_t || s.reserved_capacity_t);
  table($("schedule"), ["Год", "Канал", "Доступен с", "Бронь", "Заказ", "План", "Факт", "Оплач. объём", "Цена", "Закупка", "За бронь", "Заказать до"],
    sched.map((s) => [s.year, `${s.source_id} ${s.name}`, s.available_from, fmt(s.reserved_capacity_t, 0), fmt(s.ordered_t, 0), fmt(s.delivered_plan_t), fmt(s.delivered_actual_t), fmt(s.payable_volume_t), fmt(s.price_mln_per_t, 2), fmt(s.variable_payment_mln), fmt(s.reservation_payment_mln), s.order_by]),
    (r) => (r[6] !== r[5] ? "info" : ""));
}

async function compare() {
  setStatus("Сравниваю BASE и MANDATORY_STRESS…", "wait");
  try {
    const cmp = await api("/api/compare", { plan: readPlan(), scenarios: ["BASE", "MANDATORY_STRESS"] });
    showError(null);
    $("sec-compare").classList.remove("hidden");
    const ids = cmp.scenarios;
    table($("compare-totals"), ["Показатель", ...ids, "Разница"],
      cmp.totals.map((r) => [r.metric, ...ids.map((s) => fmt(r[s], 2)), fmt(r["delta:" + ids[1]], 2)]));
    const keep = new Set(["demand_total_t", "delivered_actual_t", "served_total_t", "shortage_total_t", "closing_stock_t", "reserve_equivalent_days", "total_mln", "pv_mln"]);
    table($("compare-yearly"), ["Год", "Показатель", ...ids, "Разница"],
      cmp.yearly.filter((r) => keep.has(r.metric)).map((r) => [r.year, r.metric, ...ids.map((s) => fmt(r[s], 1)), fmt(r["delta:" + ids[1]], 1)]),
      (r) => (r[1] === "shortage_total_t" && parseFloat(String(r[3]).replace(",", ".")) > 0 ? "bad" : ""));
    const f = cmp.feasible;
    setStatus(`BASE: ${f.BASE ? "исполним" : "НЕ исполним"} · MANDATORY_STRESS: ${f.MANDATORY_STRESS ? "исполним" : "НЕ исполним"} — таблица сравнения внизу`, f.BASE && f.MANDATORY_STRESS ? "ok" : "bad");
    $("sec-compare").scrollIntoView({ behavior: "smooth" });
  } catch (e) { showError(e); }
}

async function save() {
  try {
    const r = await api("/api/plans", { plan: readPlan() });
    showError(null);
    renderPlanList(r.plans, r.plan_id);
    setStatus(`Сохранено: results/plans/${r.saved}`, "ok");
  } catch (e) { showError(e); }
}

async function open() {
  const id = $("plan-list").value;
  if (!id) return;
  try {
    const plan = await api(`/api/plans/${encodeURIComponent(id)}`);
    fillForm(plan);
    showError(null);
    await calc();
  } catch (e) { showError(e); }
}

async function exportFile(format) {
  try {
    const res = await api(`/api/export?format=${format}&scenario=${encodeURIComponent($("scenario").value)}`, { plan: readPlan() }, true);
    const blob = await res.blob();
    const name = (res.headers.get("Content-Disposition") || "").match(/filename="(.+)"/)?.[1] || `export.${format}`;
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = name;
    a.click();
    setStatus(`Выгрузка ${name} готова`, "ok");
  } catch (e) { showError(e); }
}

function renderPlanList(plans, selected) {
  $("plan-list").innerHTML = plans.map((p) => `<option value="${p.file.replace(/\.json$/, "")}" ${p.plan_id === selected ? "selected" : ""}>${p.plan_id}${p.label ? " — " + p.label : ""}</option>`).join("");
}

async function init() {
  $("btn-calc").onclick = calc;
  $("btn-compare").onclick = compare;
  $("btn-save").onclick = save;
  $("btn-open").onclick = open;
  $("btn-csv").onclick = () => exportFile("csv");
  $("btn-xlsx").onclick = () => exportFile("xlsx");
  $("btn-reset").onclick = reset;
  try {
    state.inputs = await api("/api/inputs");
  } catch (e) { showError(e); return; }
  buildEditor();
  renderSources();
  renderPlanList(state.inputs.plans, "base-v1");
  if (state.inputs.plans.some((p) => p.plan_id === "base-v1")) { $("plan-list").value = "base-v1"; await open(); } else await calc();
}

init();
