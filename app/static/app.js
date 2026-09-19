const $ = (id) => document.getElementById(id);
const state = { inputs: null, result: null, scenario: "BASE" };

const RULES = {
  BASE_CRITICAL_SERVICE: "Сервис критического спроса",
  BASE_TOTAL_SERVICE: "Сервис общего спроса",
  CAPEX_2037: "Лимит CAPEX до 2037",
  CAPEX_2040: "Лимит CAPEX до 2040",
  RESERVE_45D: "Резерв 45 дней",
  EMERGENCY_BASE_STREAK: "Emergency как основной канал",
  STRESS_LOSS_LIMIT: "Потолок потерь",
  CAPACITY_EXCEEDED: "Превышена мощность",
  ORDER_EXCEEDS_RESERVATION: "Заказ больше брони",
  SOURCE_UNAVAILABLE: "Канал недоступен",
  STORAGE_CAPACITY: "Переполнение бака",
  ISRU_FINANCING: "Финансирование ISRU",
  INVESTMENT_NOT_AVAILABLE: "Инвестиция недоступна",
};

const METRICS = {
  pv_total_mln: ["Затраты PV, млн", 0],
  total_cost_mln: ["Затраты всего, млн", 0],
  capex_total_mln: ["CAPEX, млн", 0],
  served_total_t: ["Выдано, т", 1],
  shortage_total_t: ["Дефицит, т", 1],
  cost_per_served_t_mln: ["Стоимость тонны, млн", 2],
  min_service_level_critical: ["Мин. сервис критического спроса", 3],
};

const UNITS = { month: "мес", week: "нед", day: "дн" };

const num = (v, d = 1) => (typeof v === "number" ? v.toLocaleString("ru-RU", { minimumFractionDigits: d, maximumFractionDigits: d }) : v ?? "");
const pct = (v) => (typeof v === "number" ? num(v * 100, 1) + " %" : "");
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

async function api(path, body, raw) {
  const res = await fetch(path, body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (raw) {
    if (!res.ok) throw await res.json();
    return res;
  }
  const data = await res.json();
  if (!res.ok) throw data;
  return data;
}

function setStatus(text, cls) {
  const s = $("status");
  s.textContent = text;
  s.className = "status " + (cls || "");
}

function showError(err) {
  const box = $("error");
  document.body.classList.toggle("stale", !!err);
  if (!err) {
    box.classList.add("hidden");
    box.textContent = "";
    return;
  }
  box.textContent = err.error === "INVALID_PLAN"
    ? err.details.map((d) => `${d.path}: ${d.message}`).join("\n")
    : err.message || err.error || String(err);
  box.classList.remove("hidden");
  setStatus(err.error === "INVALID_PLAN" ? "План не принят, расчёта нет" : "Ошибка", "bad");
  $("overview").scrollIntoView({ block: "start" });
}

function table(el, header, rows, rowClass) {
  const th = header.map((h) => `<th class="${h.startsWith("~") ? "txt" : ""}">${h.replace("~", "")}</th>`).join("");
  const body = rows.map((r) => `<tr class="${rowClass ? rowClass(r) : ""}">${r.map((c) => `<td class="${typeof c === "string" && c.replace(/<[^>]+>/g, "").length > 14 ? "txt" : ""}">${c ?? ""}</td>`).join("")}</tr>`).join("");
  el.innerHTML = `<thead><tr>${th}</tr></thead><tbody>${body}</tbody>`;
}

function niceStep(top) {
  const steps = [1, 2, 5, 10, 20, 25, 50, 100, 200, 250, 500, 1000];
  return steps.find((s) => top / s <= 6) || 1000;
}

function chartStock(res) {
  const m = res.monthly_trace;
  const W = 1000, H = 260, L = 44, R = 12, T = 14, B = 30;
  const top = Math.max(...m.map((r) => Math.max(r.capacity_t, r.closing_t))) * 1.08 || 1;
  const x = (i) => L + (i / (m.length - 1)) * (W - L - R);
  const y = (v) => T + (1 - v / top) * (H - T - B);
  const years = [...new Set(m.map((r) => r.year))];
  const per = m.length / years.length;
  const step = niceStep(top);
  const w = (W - L - R) / (m.length - 1);
  const line = m.map((r, i) => (i ? "L" : "M") + x(i).toFixed(1) + " " + y(r.closing_t).toFixed(1)).join(" ");
  let s = `<svg viewBox="0 0 ${W} ${H}">`;
  for (let v = 0; v <= top; v += step) s += `<line x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}" stroke="#eceef1"/><text x="${L - 8}" y="${y(v) + 4}" text-anchor="end" font-size="11" fill="#6f7681">${v}</text>`;
  years.forEach((yr, k) => {
    const xx = x(k * per);
    s += `<line x1="${xx}" x2="${xx}" y1="${T}" y2="${H - B}" stroke="#eceef1"/><text x="${x(k * per + per / 2)}" y="${H - 10}" text-anchor="middle" font-size="12" fill="#6f7681">${yr}</text>`;
  });
  s += `<path d="${line} L${x(m.length - 1).toFixed(1)} ${y(0)} L${x(0)} ${y(0)} Z" fill="#1f5fbf" opacity="0.07"/>`;
  s += `<path d="${m.map((r, i) => (i ? "L" : "M") + x(i).toFixed(1) + " " + y(r.capacity_t).toFixed(1)).join(" ")}" fill="none" stroke="#9aa3b2" stroke-dasharray="4 4"/>`;
  s += `<path d="${line}" fill="none" stroke="#1f5fbf" stroke-width="2"/>`;
  m.forEach((r, i) => {
    if (r.shortage_t > 0) s += `<rect x="${(x(i) - 3).toFixed(1)}" y="${H - B - 6}" width="6" height="6" fill="#b3261e"/>`;
    s += `<rect x="${(x(i) - w / 2).toFixed(1)}" y="${T}" width="${w.toFixed(1)}" height="${H - T - B}" fill="transparent"><title>${r.period}: остаток ${num(r.closing_t)} т из ${num(r.capacity_t, 0)}, дефицит ${num(r.shortage_t)} т</title></rect>`;
  });
  $("chart-stock").innerHTML = s + "</svg>";
}

function chartDemand(res) {
  const rows = res.yearly_balance;
  const W = 1000, H = 240, L = 44, R = 12, T = 14, B = 30;
  const top = Math.max(...rows.map((r) => Math.max(r.demand_total_t, r.delivered_actual_t, r.served_total_t))) * 1.1 || 1;
  const y = (v) => T + (1 - v / top) * (H - T - B);
  const slot = (W - L - R) / rows.length;
  const bw = Math.min(28, slot / 4);
  const step = niceStep(top);
  let s = `<svg viewBox="0 0 ${W} ${H}">`;
  for (let v = 0; v <= top; v += step) s += `<line x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}" stroke="#eceef1"/><text x="${L - 8}" y="${y(v) + 4}" text-anchor="end" font-size="11" fill="#6f7681">${v}</text>`;
  rows.forEach((r, k) => {
    const cx = L + slot * (k + 0.5);
    const bars = [[r.demand_total_t, "#d5d9e0"], [r.delivered_actual_t, "#9cc0ee"], [r.served_total_t, "#1f5fbf"]];
    bars.forEach(([v, c], j) => {
      const bx = cx + (j - 1.5) * bw;
      s += `<rect x="${bx.toFixed(1)}" y="${y(v).toFixed(1)}" width="${(bw - 2).toFixed(1)}" height="${(y(0) - y(v)).toFixed(1)}" rx="2" fill="${c}"><title>${r.year}: спрос ${num(r.demand_total_t)} т, приехало ${num(r.delivered_actual_t)} т, выдано ${num(r.served_total_t)} т, дефицит ${num(r.shortage_total_t)} т</title></rect>`;
    });
    if (r.shortage_total_t > 0) s += `<text x="${cx}" y="${y(r.demand_total_t) - 6}" text-anchor="middle" font-size="12" fill="#b3261e">−${num(r.shortage_total_t)}</text>`;
    s += `<text x="${cx}" y="${H - 10}" text-anchor="middle" font-size="12" fill="#6f7681">${r.year}</text>`;
  });
  $("chart-demand").innerHTML = s + "</svg>";
}

function renderSummary(res) {
  const t = res.totals;
  const minReserve = Math.min(...res.yearly_balance.map((r) => r.reserve_equivalent_days));
  const items = [
    ["Затраты PV, млн", num(t.pv_total_mln, 0)],
    ["Затраты всего, млн", num(t.total_cost_mln, 0)],
    ["CAPEX, млн", num(t.capex_total_mln, 0)],
    ["Дефицит, т", num(t.shortage_total_t, 1), t.shortage_total_t > 0],
    ["Мин. резерв, дней", num(Math.min(minReserve, 999), 0), minReserve < 45],
    ["Стоимость тонны, млн", num(t.cost_per_served_t_mln, 2)],
  ];
  $("summary").innerHTML = items.map(([l, v, bad]) => `<div class="figure ${bad ? "bad" : ""}"><span>${l}</span><b>${v}</b></div>`).join("");
  $("summary").classList.remove("hidden");
}

function renderViolations(res) {
  const bad = res.constraint_checks.filter((c) => !c.ok);
  const hard = bad.filter((c) => c.severity === "hard");
  $("violations").innerHTML = bad.length
    ? bad.map((c) => `<li class="${c.severity === "hard" ? "" : "info"}"><span class="y">${c.year}</span><span class="r">${RULES[c.rule_id] || c.rule_id}</span>${esc(c.reason)}${c.severity === "hard" ? "" : ' <span class="muted">справочно</span>'}</li>`).join("")
    : '<li class="none">Нет</li>';
  $("warnings").textContent = (res.warnings || []).join(". ");
  return hard.length;
}

function renderTables(res) {
  table($("balance-table"), ["Год", "Спрос", "Приехало", "Потери", "Выдано", "Дефицит", "Остаток", "Резерв, дней", "Сервис крит."],
    res.yearly_balance.map((r) => [r.year, num(r.demand_total_t), num(r.delivered_actual_t), num(r.losses_t, 2), num(r.served_total_t), num(r.shortage_total_t), num(r.closing_stock_t), num(Math.min(r.reserve_equivalent_days, 999), 0), pct(r.service_level_critical)]),
    (r) => (r[5] !== num(0) ? "bad" : ""));
  const sched = res.source_schedule.filter((s) => s.ordered_t || s.reserved_capacity_t);
  table($("schedule-table"), ["Год", "~Канал", "Бронь", "Заказ", "План", "Факт", "Цена", "Закупка", "За бронь", "Заказать до"],
    sched.map((s) => [s.year, `${s.source_id} · ${esc(s.name)}`, num(s.reserved_capacity_t, 0), num(s.ordered_t, 0), num(s.delivered_plan_t), num(s.delivered_actual_t), num(s.price_mln_per_t, 2), num(s.variable_payment_mln), num(s.reservation_payment_mln), s.order_by.length > 7 ? `<span title="${esc(s.order_by)}">заранее</span>` : s.order_by]));
  const f = res.financial_breakdown;
  const t = res.totals;
  const rows = f.map((r) => [r.year, num(r.procurement_mln), num(r.reservation_mln), num(r.holding_mln), num(r.fixed_opex_mln, 0), num(r.capex_mln, 0), num(r.initial_stock_mln), num(r.total_mln), num(r.pv_mln)]);
  rows.push(["Итого", num(t.procurement_mln), num(t.reservation_mln), num(t.holding_mln), num(t.fixed_opex_mln, 0), num(t.capex_total_mln, 0), num(f.reduce((a, r) => a + r.initial_stock_mln, 0)), num(t.total_cost_mln), num(t.pv_total_mln)]);
  table($("finance-table"), ["Год", "Закупка", "Бронь", "Хранение", "OPEX", "CAPEX", "Стартовый запас", "Итого", "PV"], rows, (r) => (r[0] === "Итого" ? "total" : ""));
}

function render(res) {
  state.result = res;
  const hard = renderViolations(res);
  setStatus(`${res.plan_id} · ${res.scenario_id}: ${res.feasible ? "план исполним" : `план не исполним, нарушений: ${hard}`}`, res.feasible ? "ok" : "bad");
  renderSummary(res);
  chartStock(res);
  chartDemand(res);
  renderTables(res);
  $("engine").textContent = res.meta.engine_version;
}

function grid(el, kind, sources, years) {
  el.innerHTML = `<thead><tr><th>Канал</th>${years.map((y) => `<th>${y}</th>`).join("")}</tr></thead><tbody>${sources.map((s) => `<tr><td>${s.id} · ${esc(s.name)} <span class="muted">до ${num(s.capacity, 0)}</span></td>${years.map((y) => `<td><input data-kind="${kind}" data-src="${s.id}" data-year="${y}" type="number" min="0" step="1" placeholder="0"></td>`).join("")}</tr>`).join("")}</tbody>`;
}

function yearOptions(sel, years, value) {
  sel.innerHTML = years.map((y) => `<option value="${y}" ${y === value ? "selected" : ""}>${y}</option>`).join("");
}

function setScenario(id, recalc) {
  state.scenario = id;
  document.querySelectorAll("#scenario button").forEach((b) => b.classList.toggle("on", b.dataset.id === id));
  if (recalc) calc();
}

function buildEditor() {
  const { years, sources, scenarios } = state.inputs;
  grid($("orders"), "order", sources, years);
  grid($("reservations"), "res", sources, years);
  yearOptions($("en-option"), years, 2035);
  yearOptions($("en-exercise"), years, 2036);
  yearOptions($("zbo-year"), years, 2037);
  $("isru-years").innerHTML = years.map((y) => `<label><input type="checkbox" class="isru-year" value="${y}">${y}</label>`).join("");
  $("init-source").innerHTML = sources.map((s) => `<option value="${s.id}">${s.id} · ${esc(s.name)}, ${num(s.price, 2)} млн/т</option>`).join("");
  $("scenario").innerHTML = scenarios.map((s) => `<button type="button" data-id="${s.scenario_id}" title="${esc(s.label)}">${s.scenario_id}</button>`).join("");
  $("scenario").addEventListener("click", (e) => { if (e.target.dataset.id) setScenario(e.target.dataset.id, true); });
  setScenario(scenarios.some((s) => s.scenario_id === "BASE") ? "BASE" : scenarios[0].scenario_id);
  const plan = $("plan");
  plan.addEventListener("input", () => setStatus("План изменён, нажмите «Посчитать»", "wait"));
  plan.addEventListener("keydown", (e) => { if (e.key === "Enter" && e.target.tagName === "INPUT") calc(); });
  table($("sources-table"), ["~Канал", "Мощность, т/год", "Цена, млн/т", "Бронь, млн за т", "Take-or-pay", "Срок заказа", "Доступен с", "Надёжность", "~Примечание"],
    sources.map((s) => [`${s.id} · ${esc(s.name)}`, num(s.capacity, 0), num(s.price, 2), num(s.reservation_rate, 2), pct(s.top_share), `${s.lead_time_min === s.lead_time_max ? s.lead_time_max : `${s.lead_time_min}–${s.lead_time_max}`} ${UNITS[s.lead_time_unit] || s.lead_time_unit}`, s.available_from ?? "после инвестиции", num(s.reliability, 2), esc(s.notes)]));
}

function readPlan() {
  const orders = [], reservations = [];
  document.querySelectorAll("#orders input, #reservations input").forEach((el) => {
    if (el.value === "") return;
    const row = { source_id: el.dataset.src, year: Number(el.dataset.year) };
    if (el.dataset.kind === "order") orders.push({ ...row, ordered_t: Number(el.value) });
    else reservations.push({ ...row, reserved_capacity_t: Number(el.value) });
  });
  const investments = [];
  if ($("en-on").checked) investments.push({ investment_id: "EARTH_NEW", option_year: Number($("en-option").value), exercise_year: Number($("en-exercise").value) });
  if ($("isru-on").checked) investments.push({ investment_id: "LUNAR_ISRU", financing_years: [...document.querySelectorAll(".isru-year:checked")].map((e) => Number(e.value)) });
  if ($("zbo-on").checked) investments.push({ investment_id: "ZBO", year: Number($("zbo-year").value) });
  return {
    plan_id: $("plan-id").value.trim() || "plan",
    scenario_id: state.scenario,
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
  if (plan.scenario_id && state.inputs.scenarios.some((s) => s.scenario_id === plan.scenario_id)) setScenario(plan.scenario_id);
  document.querySelectorAll("#orders input, #reservations input").forEach((el) => (el.value = ""));
  const d = plan.decisions || {};
  (d.supply_orders || []).forEach((o) => { const el = document.querySelector(`#orders input[data-src="${o.source_id}"][data-year="${o.year}"]`); if (el) el.value = o.ordered_t; });
  (d.capacity_reservations || []).forEach((r) => { const el = document.querySelector(`#reservations input[data-src="${r.source_id}"][data-year="${r.year}"]`); if (el) el.value = r.reserved_capacity_t; });
  const inv = Object.fromEntries((d.investments || []).map((i) => [i.investment_id, i]));
  $("en-on").checked = !!inv.EARTH_NEW;
  if (inv.EARTH_NEW) { $("en-option").value = inv.EARTH_NEW.option_year; $("en-exercise").value = inv.EARTH_NEW.exercise_year; }
  $("isru-on").checked = !!inv.LUNAR_ISRU;
  const years = new Set(inv.LUNAR_ISRU ? inv.LUNAR_ISRU.financing_years || [inv.LUNAR_ISRU.year] : []);
  document.querySelectorAll(".isru-year").forEach((e) => (e.checked = years.has(Number(e.value))));
  $("zbo-on").checked = !!inv.ZBO;
  if (inv.ZBO) $("zbo-year").value = inv.ZBO.year;
  const ip = d.inventory_policy || {};
  $("init-stock").value = ip.initial_stock_t ?? 0;
  $("init-cost").value = ip.initial_stock_cost_mln ?? 0;
  if (ip.initial_stock_source_id) $("init-source").value = ip.initial_stock_source_id;
}

async function calc() {
  setStatus("Считаю…", "wait");
  try {
    const res = await api("/api/calculate", { plan: readPlan(), scenario_id: state.scenario });
    showError(null);
    render(res);
  } catch (e) { showError(e); }
}

async function compare() {
  setStatus("Считаю оба сценария…", "wait");
  try {
    const cmp = await api("/api/compare", { plan: readPlan(), scenarios: ["BASE", "MANDATORY_STRESS"] });
    showError(null);
    const ids = cmp.scenarios;
    const rows = [["Исполним", ...ids.map((s) => (cmp.feasible[s] ? "да" : "нет")), ""]];
    cmp.totals.filter((r) => METRICS[r.metric]).forEach((r) => {
      const [label, d] = METRICS[r.metric];
      const f = r.metric.startsWith("min_service") ? pct : (v) => num(v, d);
      rows.push([label, ...ids.map((s) => f(r[s])), f(r["delta:" + ids[1]])]);
    });
    cmp.yearly.filter((r) => r.metric === "shortage_total_t").forEach((r) => rows.push([`Дефицит ${r.year}, т`, ...ids.map((s) => num(r[s])), num(r["delta:" + ids[1]])]));
    cmp.yearly.filter((r) => r.metric === "reserve_equivalent_days").forEach((r) => rows.push([`Резерв ${r.year}, дней`, ...ids.map((s) => num(Math.min(r[s], 999), 0)), ""]));
    table($("compare-table"), ["~Показатель", ...ids, "Разница"], rows, (r) => (r[0] === "Исполним" && r.includes("нет") ? "bad" : ""));
    $("compare").classList.remove("hidden");
    setStatus(`BASE: ${cmp.feasible.BASE ? "исполним" : "не исполним"} · MANDATORY_STRESS: ${cmp.feasible.MANDATORY_STRESS ? "исполним" : "не исполним"}`, cmp.feasible.BASE && cmp.feasible.MANDATORY_STRESS ? "ok" : "bad");
    $("compare").scrollIntoView({ block: "start" });
  } catch (e) { showError(e); }
}

function renderPlanList(plans, selected) {
  $("plan-list").innerHTML = plans.map((p) => `<option value="${esc(p.file.replace(/\.json$/, ""))}" ${p.plan_id === selected ? "selected" : ""}>${esc(p.plan_id)}</option>`).join("");
}

async function save() {
  try {
    const r = await api("/api/plans", { plan: readPlan() });
    showError(null);
    renderPlanList(r.plans, r.plan_id);
    setStatus(`Сохранено: results/plans/${r.saved}`, "ok");
  } catch (e) { showError(e); }
}

async function openPlan() {
  const id = $("plan-list").value;
  if (!id) return;
  try {
    const plan = await api(`/api/plans/${encodeURIComponent(id)}`);
    fillForm(plan);
    showError(null);
    await calc();
  } catch (e) { showError(e); }
}

async function loadFile(ev) {
  const file = ev.target.files[0];
  if (!file) return;
  let plan;
  try {
    plan = JSON.parse(await file.text());
  } catch (e) {
    showError({ message: `${file.name}: это не JSON (${e.message})` });
    return;
  }
  if (!plan || typeof plan !== "object" || !plan.decisions) {
    showError({ message: `${file.name}: в файле нет поля decisions, это не план` });
    return;
  }
  fillForm(plan);
  ev.target.value = "";
  await calc();
}

function downloadPlan() {
  const plan = readPlan();
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([JSON.stringify(plan, null, 2)], { type: "application/json" }));
  a.download = `${plan.plan_id}.json`;
  a.click();
}

async function exportFile(format) {
  try {
    const res = await api(`/api/export?format=${format}&scenario=${encodeURIComponent(state.scenario)}`, { plan: readPlan() }, true);
    const blob = await res.blob();
    const name = (res.headers.get("Content-Disposition") || "").match(/filename="(.+)"/)?.[1] || `export.${format}`;
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = name;
    a.click();
  } catch (e) { showError(e); }
}

function spy() {
  const links = [...document.querySelectorAll(".nav a")];
  const sections = links.map((a) => document.querySelector(a.getAttribute("href"))).filter(Boolean);
  const mark = () => {
    const line = window.scrollY + 120;
    let current = sections[0];
    sections.forEach((s) => { if (!s.classList.contains("hidden") && s.offsetTop <= line) current = s; });
    links.forEach((a) => a.classList.toggle("active", a.getAttribute("href") === "#" + current.id));
  };
  window.addEventListener("scroll", mark, { passive: true });
  mark();
  $("nav-compare").addEventListener("click", (e) => { if ($("compare").classList.contains("hidden")) { e.preventDefault(); compare(); } });
}

async function init() {
  $("btn-calc").onclick = calc;
  $("btn-calc-2").onclick = calc;
  $("btn-compare").onclick = compare;
  $("btn-save").onclick = save;
  $("btn-plan").onclick = downloadPlan;
  $("btn-csv").onclick = () => exportFile("csv");
  $("btn-xlsx").onclick = () => exportFile("xlsx");
  $("plan-list").onchange = openPlan;
  $("plan-file").addEventListener("change", loadFile);
  spy();
  try {
    state.inputs = await api("/api/inputs");
  } catch (e) { showError(e); return; }
  buildEditor();
  renderPlanList(state.inputs.plans, "base-v1");
  if (state.inputs.plans.some((p) => p.plan_id === "base-v1")) await openPlan();
  else setStatus("Выберите план или загрузите JSON", "wait");
}

init();
