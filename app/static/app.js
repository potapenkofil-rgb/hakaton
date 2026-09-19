const $ = (id) => document.getElementById(id);
const state = { inputs: null, result: null, scenario: "BASE", selectedYear: null };

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
const SHORT = { BASE: "Стандартный", MANDATORY_STRESS: "Стрессовый" };

function scenarioName(id) {
  if (SHORT[id]) return SHORT[id];
  const s = (state.inputs?.scenarios || []).find((x) => x.scenario_id === id);
  return s?.label || id;
}

const RELIABILITY = { constant: "", first_operating_year: "первый год", later: "потом" };

function reliability(raw) {
  if (typeof raw === "number") return num(raw, 2);
  return String(raw ?? "").split(";").map((part) => {
    const [k, v] = part.split(":");
    const label = k in RELIABILITY ? RELIABILITY[k] : k + ":";
    return (label ? label + " " : "") + num(Number(v), 2);
  }).join(" · ");
}

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
  if (cls === "wait") $("compare").classList.add("hidden");
}

function showError(err, { scroll = true } = {}) {
  const box = $("error");
  document.body.classList.toggle("stale", !!err);
  if (!err) {
    box.classList.add("hidden");
    box.textContent = "";
    $("calc-error").classList.add("hidden");
    $("calc-error").textContent = "";
    return;
  }
  box.textContent = err.error === "INVALID_PLAN"
    ? err.details.map((d) => `${d.path}: ${d.message}`).join("\n")
    : err.message || err.error || String(err);
  box.classList.remove("hidden");
  setStatus(err.error === "INVALID_PLAN" ? "План не принят, расчёта нет" : "Ошибка", "bad");
  if (scroll) $("overview").scrollIntoView({ block: "start" });
}

function table(el, header, rows, rowClass) {
  const th = header.map((h) => `<th scope="col" class="${h.startsWith("~") ? "txt" : ""}">${h.replace("~", "")}</th>`).join("");
  const body = rows.map((r) => `<tr class="${rowClass ? rowClass(r) : ""}">${r.map((c, i) => `<td class="${header[i].startsWith("~") ? "txt" : ""}">${c ?? ""}</td>`).join("")}</tr>`).join("");
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
  for (let v = 0; v <= top; v += step) s += `<line x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}" stroke="#eceef1"/><text x="${L - 8}" y="${y(v) + 4}" text-anchor="end" font-size="13" fill="#6f7681">${v}</text>`;
  years.forEach((yr, k) => {
    const xx = x(k * per);
    s += `<line x1="${xx}" x2="${xx}" y1="${T}" y2="${H - B}" stroke="#eceef1"/><text x="${x(k * per + per / 2)}" y="${H - 10}" text-anchor="middle" font-size="13" fill="#6f7681">${yr}</text>`;
  });
  s += `<path d="${line} L${x(m.length - 1).toFixed(1)} ${y(0)} L${x(0)} ${y(0)} Z" fill="#1f5fbf" opacity="0.07"/>`;
  s += `<path d="${m.map((r, i) => (i ? "L" : "M") + x(i).toFixed(1) + " " + y(r.capacity_t).toFixed(1)).join(" ")}" fill="none" stroke="#9aa3b2" stroke-dasharray="4 4"/>`;
  s += `<path d="${line}" fill="none" stroke="#1f5fbf" stroke-width="2"/>`;
  m.forEach((r, i) => {
    if (r.shortage_t > 0) s += `<rect x="${(x(i) - 3).toFixed(1)}" y="${H - B - 6}" width="6" height="6" fill="#b3261e"/>`;
    if (r.month === 12) s += `<circle cx="${x(i).toFixed(1)}" cy="${y(r.closing_t).toFixed(1)}" r="4" fill="#fff" stroke="#1f5fbf" stroke-width="2"/><text x="${x(i).toFixed(1)}" y="${(y(r.closing_t) - 10).toFixed(1)}" text-anchor="middle" font-size="13" fill="#16181d">${num(r.closing_t, 0)}</text>`;
  });
  s += `<g class="hover" style="display:none"><line y1="${T}" y2="${H - B}" stroke="#16181d" stroke-width="1" stroke-dasharray="3 3"/><circle r="5" fill="#1f5fbf" stroke="#fff" stroke-width="2"/><rect height="22" rx="4" fill="#16181d"/><text font-size="13" fill="#fff"></text></g>`;
  s += `<rect x="${L}" y="${T}" width="${W - L - R}" height="${H - T - B}" fill="transparent" class="hit"/>`;
  $("chart-stock").innerHTML = s + "</svg>";
  hoverStock(m, { W, L, R, T, x, y });
}

const MONTHS = ["янв", "фев", "мар", "апр", "май", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"];

function hoverStock(m, g) {
  const svg = $("chart-stock").querySelector("svg");
  const box = svg.querySelector(".hover");
  const [guide, dot, bg, text] = box.children;
  svg.addEventListener("mousemove", (e) => {
    const r = svg.getBoundingClientRect();
    const px = ((e.clientX - r.left) / r.width) * g.W;
    const i = Math.max(0, Math.min(m.length - 1, Math.round(((px - g.L) / (g.W - g.L - g.R)) * (m.length - 1))));
    const row = m[i];
    const cx = g.x(i), cy = g.y(row.closing_t);
    let label = `${MONTHS[row.month - 1]} ${row.year} · ${num(row.closing_t)} т`;
    if (row.shortage_t > 0) label += ` · дефицит ${num(row.shortage_t)} т`;
    text.textContent = label;
    const tw = text.getComputedTextLength() + 16;
    const left = cx + tw + 12 > g.W - g.R;
    const bx = left ? cx - tw - 10 : cx + 10;
    const by = Math.max(g.T, cy - 32);
    guide.setAttribute("x1", cx); guide.setAttribute("x2", cx);
    dot.setAttribute("cx", cx); dot.setAttribute("cy", cy);
    bg.setAttribute("x", bx); bg.setAttribute("y", by); bg.setAttribute("width", tw);
    text.setAttribute("x", bx + 8); text.setAttribute("y", by + 15);
    box.style.display = "";
  });
  svg.addEventListener("mouseleave", () => { box.style.display = "none"; });
}

function selectBalanceYear() {
  document.querySelectorAll("#balance-table tbody tr").forEach((row) => {
    row.classList.toggle("selected-year", Number(row.cells[0].textContent) === state.selectedYear);
  });
}

function chartDemand(res) {
  const rows = res.yearly_balance;
  if (!rows.some((r) => r.year === state.selectedYear)) state.selectedYear = null;
  const W = 1000, H = 300, L = 50, R = 16, T = 38, B = 36;
  const top = Math.max(...rows.map((r) => Math.max(r.demand_total_t, r.delivered_actual_t, r.served_total_t))) * 1.16 || 1;
  const y = (v) => T + (1 - v / top) * (H - T - B);
  const slot = (W - L - R) / rows.length;
  const bw = Math.min(30, slot / 4);
  const series = [
    ["demand_total_t", "Спрос", "#aab5c5"],
    ["delivered_actual_t", "Фактически приехало", "#78a9e6"],
    ["served_total_t", "Фактически выдано", "#1f5fbf"],
  ];
  let s = `<svg viewBox="0 0 ${W} ${H}" role="group" aria-label="Спрос и выдача по годам, тонны">`;
  for (let v = 0; v <= top; v += niceStep(top)) s += `<line x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}" stroke="#dfe5ec"/><text x="${L - 8}" y="${y(v) + 4}" text-anchor="end" class="axis-label">${v}</text>`;
  rows.forEach((r, k) => {
    const cx = L + slot * (k + 0.5);
    s += `<g class="demand-year" data-year="${r.year}"><rect class="year-highlight" x="${L + slot * k + 3}" y="4" width="${slot - 6}" height="${H - 5}" rx="6"/>`;
    const itemAttrs = (metric, label) => `class="demand-item" data-metric="${metric}" data-label="${label}" tabindex="0" role="button" aria-pressed="false" aria-label="${r.year}: ${label}, ${num(r[metric])} т"`;
    series.forEach(([metric, label, c], j) => {
      const v = r[metric];
      s += `<rect ${itemAttrs(metric, label)} x="${cx + (j - 1.5) * bw}" y="${y(v)}" width="${bw - 3}" height="${y(0) - y(v)}" rx="2" fill="${c}"/>`;
    });
    if (r.shortage_total_t > 0) s += `<text ${itemAttrs("shortage_total_t", "Дефицит")} x="${cx}" y="${y(r.demand_total_t) - 9}" text-anchor="middle" fill="#b3261e" font-size="13" font-weight="600">Дефицит ${num(r.shortage_total_t)} т</text>`;
    s += `<text x="${cx}" y="${H - 12}" text-anchor="middle" class="axis-label">${r.year}</text></g>`;
  });
  const host = $("chart-demand");
  host.innerHTML = s + '</svg><div id="demand-tooltip" class="chart-tooltip" role="tooltip" hidden></div>';
  const tip = $("demand-tooltip");
  const groups = [...host.querySelectorAll(".demand-year")];
  const items = [...host.querySelectorAll(".demand-item")];
  let hovered = null, focused = null;
  function update() {
    const active = hovered ?? focused;
    const activeYear = active ? Number(active.closest(".demand-year").dataset.year) : null;
    groups.forEach((g) => {
      const year = Number(g.dataset.year);
      g.classList.toggle("selected", year === state.selectedYear);
      g.classList.toggle("hovered", year === activeYear);
    });
    items.forEach((item) => {
      item.setAttribute("aria-pressed", String(Number(item.closest(".demand-year").dataset.year) === state.selectedYear));
      if (item === active) item.setAttribute("aria-describedby", "demand-tooltip");
      else item.removeAttribute("aria-describedby");
    });
    tip.hidden = active === null;
    if (active === null) return;
    const row = rows.find((r) => r.year === activeYear);
    tip.innerHTML = `<b>${activeYear}</b><dl><dt>${active.dataset.label}</dt><dd>${num(row[active.dataset.metric])} т</dd></dl>`;
    const bounds = active.getBoundingClientRect(), container = host.getBoundingClientRect();
    const center = bounds.left - container.left + bounds.width / 2;
    tip.style.left = `${Math.max(0, Math.min(host.clientWidth - tip.offsetWidth, center - tip.offsetWidth / 2))}px`;
    tip.style.top = `${Math.max(0, bounds.top - container.top - tip.offsetHeight - 8)}px`;
  }
  items.forEach((item) => {
    item.addEventListener("mouseenter", () => { hovered = item; focused = null; update(); });
    item.addEventListener("mouseleave", () => { hovered = null; update(); });
    item.addEventListener("focus", () => { if (item.matches(":focus-visible")) focused = item; update(); });
    item.addEventListener("blur", () => { focused = null; update(); });
  });
  groups.forEach((g) => {
    const year = Number(g.dataset.year);
    const toggle = () => { state.selectedYear = state.selectedYear === year ? null : year; selectBalanceYear(); update(); };
    g.addEventListener("click", toggle);
    g.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggle(); }
      if (e.key === "Escape") { state.selectedYear = null; hovered = null; focused = null; selectBalanceYear(); update(); }
    });
  });
  update();
}

function formatOrderBy(raw) {
  const value = String(raw ?? "").trim();
  if (!value) return "—";
  const date = /^(\d{4})-(0[1-9]|1[0-2])$/.exec(value);
  const horizon = /^до начала горизонта \((\d{4})\)/.exec(value);
  const label = date ? `${MONTHS[Number(date[2]) - 1]}. ${date[1]}` : horizon ? `до начала ${horizon[1]}` : value;
  return `<span title="${esc(value)}">${esc(label)}</span>`;
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
  table($("schedule-table"), ["Год", "~Канал", "Бронь мощности, т", "Заказ, т", "План поставки, т", "Факт поставки, т", "Цена, млн/т", "Оплата поставки, млн", "Плата за бронь, млн", "~Разместить заказ не позднее"],
    sched.map((s) => [s.year, `${s.source_id} · ${esc(s.name)}`, num(s.reserved_capacity_t, 0), num(s.ordered_t, 0), num(s.delivered_plan_t), num(s.delivered_actual_t), num(s.price_mln_per_t, 2), num(s.variable_payment_mln), num(s.reservation_payment_mln), formatOrderBy(s.order_by)]));
  const f = res.financial_breakdown;
  const t = res.totals;
  const rows = f.map((r) => [r.year, num(r.procurement_mln), num(r.reservation_mln), num(r.holding_mln), num(r.fixed_opex_mln, 0), num(r.capex_mln, 0), num(r.initial_stock_mln), num(r.total_mln), num(r.pv_mln)]);
  rows.push(["Итого", num(t.procurement_mln), num(t.reservation_mln), num(t.holding_mln), num(t.fixed_opex_mln, 0), num(t.capex_total_mln, 0), num(f.reduce((a, r) => a + r.initial_stock_mln, 0)), num(t.total_cost_mln), num(t.pv_total_mln)]);
  table($("finance-table"), ["Год", "Закупка", "Бронь", "Хранение", "OPEX", "CAPEX", "Стартовый запас", "Итого", "PV"], rows, (r) => (r[0] === "Итого" ? "total" : ""));
}

function render(res) {
  state.result = res;
  const hard = renderViolations(res);
  const edited = Object.keys(res.meta.overrides || {}).length ? " · данные изменены" : "";
  setStatus(`${res.plan_id} · ${SHORT[res.scenario_id] ? `${scenarioName(res.scenario_id).toLowerCase()} сценарий` : `сценарий «${scenarioName(res.scenario_id)}»`}${edited}: ${res.feasible ? "план исполним" : `план не исполним, нарушений: ${hard}`}`, res.feasible ? "ok" : "bad");
  renderSummary(res);
  chartStock(res);
  chartDemand(res);
  renderTables(res);
  selectBalanceYear();
}

function grid(el, kind, sources, years) {
  el.innerHTML = `<thead><tr><th>Канал</th>${years.map((y) => `<th>${y}</th>`).join("")}</tr></thead><tbody>${sources.map((s) => `<tr><td>${s.id} · ${esc(s.name)} <span class="muted">до ${num(s.capacity, 0)}</span></td>${years.map((y) => `<td><input data-kind="${kind}" data-src="${s.id}" data-year="${y}" type="number" min="0" step="1" placeholder="0"></td>`).join("")}</tr>`).join("")}</tbody>`;
}

function yearOptions(sel, years, value) {
  sel.innerHTML = years.map((y) => `<option value="${y}" ${y === value ? "selected" : ""}>${y}</option>`).join("");
}

function isTeam(id) {
  return id.startsWith("TEAM_");
}

function setScenario(id, recalc) {
  state.scenario = id;
  document.querySelectorAll("#scenario button").forEach((b) => b.classList.toggle("on", b.dataset.id === id));
  $("scenario-team").value = isTeam(id) ? id : "";
  $("scenario-team").classList.toggle("on", isTeam(id));
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
  const open = sources.filter((s) => s.available_from != null && s.available_from <= years[0]);
  $("init-source").innerHTML = open.map((s) => `<option value="${s.id}">${s.id} · ${esc(s.name)}</option>`).join("");
  $("init-source").addEventListener("change", initCost);
  $("init-stock").addEventListener("input", initCost);
  const own = scenarios.filter((s) => !isTeam(s.scenario_id));
  const team = scenarios.filter((s) => isTeam(s.scenario_id));
  $("scenario").innerHTML = own.map((s) => `<button type="button" data-id="${s.scenario_id}" title="${esc(s.label)} (${s.scenario_id})">${scenarioName(s.scenario_id)}</button>`).join("");
  $("scenario").addEventListener("click", (e) => { if (e.target.dataset.id) setScenario(e.target.dataset.id, true); });
  const sel = $("scenario-team");
  sel.classList.toggle("hidden", !team.length);
  sel.innerHTML = `<option value="">Сценарий команды…</option>` + team.map((s) => `<option value="${s.scenario_id}">${esc(s.label)}</option>`).join("");
  sel.addEventListener("change", () => { if (sel.value) setScenario(sel.value, true); });
  setScenario(scenarios.some((s) => s.scenario_id === "BASE") ? "BASE" : scenarios[0].scenario_id);
  const plan = $("plan");
  plan.addEventListener("input", () => setStatus("План изменён, нажмите «Посчитать»", "wait"));
  plan.addEventListener("keydown", (e) => { if (e.key === "Enter" && e.target.tagName === "INPUT") calc(); });
  buildData();
}

function ov(kind, id, field, value, step) {
  return `<input class="ov" type="number" min="0" step="${step}" value="${value}" data-kind="${kind}" data-id="${id}" data-field="${field}" data-orig="${value}">`;
}

function current(kind, id, field) {
  const el = document.querySelector(`input.ov[data-kind="${kind}"][data-id="${id}"][data-field="${field}"]`);
  const v = el && el.value !== "" ? Number(el.value) : NaN;
  if (!Number.isNaN(v)) return v;
  const row = (state.inputs[kind] || []).find((r) => String(r.id ?? r.year) === String(id));
  return row ? row[field] : 0;
}

function initCost() {
  const stock = Number($("init-stock").value || 0);
  const price = current("sources", $("init-source").value, "price");
  $("init-cost").value = Math.round(stock * price * 1e6) / 1e6;
  $("init-source").title = `${num(price, 2)} млн/т`;
}

function hints() {
  if (!state.inputs.storages.some((s) => s.id === "ZBO")) return;
  $("zbo-capex").textContent = num(current("storages", "ZBO", "capex"), 0);
  $("zbo-hint").textContent = `бак ${num(current("storages", "ZBO", "capacity"), 0)} т, потери ${pct(current("storages", "ZBO", "loss_rate"))}, ${num(current("storages", "ZBO", "fixed_opex"), 0)} млн в год`;
}

function buildData() {
  const { years, sources, storages, demand } = state.inputs;
  table($("sources-table"), ["~Канал", "Мощность, т/год", "Цена, млн/т", "Бронь, млн за т в год", "Take-or-pay, доля", "~Срок заказа", "~Доступен с", "~Надёжность", "~Примечание"],
    sources.map((s) => [`${s.id} · ${esc(s.name)}`, ov("sources", s.id, "capacity", s.capacity, 1), ov("sources", s.id, "price", s.price, 0.1), ov("sources", s.id, "reservation_rate", s.reservation_rate, 0.01), ov("sources", s.id, "top_share", s.top_share, 0.05), `${s.lead_time_min === s.lead_time_max ? s.lead_time_max : `${s.lead_time_min}–${s.lead_time_max}`} ${UNITS[s.lead_time_unit] || s.lead_time_unit}`, s.available_from ?? "после инвестиции", reliability(s.reliability), esc(s.notes)]));
  table($("storages-table"), ["~Хранилище", "Ёмкость, т", "Потери, доля прихода", "Хранение, млн за т в год", "CAPEX, млн", "OPEX, млн в год", "Доступно с"],
    storages.map((s) => {
      const invest = s.capex > 0 || s.available_from > years[0];
      return [`${s.id} · ${esc(s.name)}`, ov("storages", s.id, "capacity", s.capacity, 1), ov("storages", s.id, "loss_rate", s.loss_rate, 0.001), ov("storages", s.id, "holding_cost", s.holding_cost, 0.01),
        invest ? ov("storages", s.id, "capex", s.capex, 1) : num(s.capex, 0), invest ? ov("storages", s.id, "fixed_opex", s.fixed_opex, 1) : num(s.fixed_opex, 0), s.available_from];
    }));
  table($("demand-table"), ["~Год", "Базовый спрос", "Критический", "Низкий (справочно)", "Высокий (справочно)"],
    demand.map((d) => [d.year, ov("demand", d.year, "total", d.total, 1), ov("demand", d.year, "critical", d.critical, 1), num(d.low_total, 0), num(d.high_total, 0)]));
  $("sources").addEventListener("input", (e) => {
    if (!e.target.classList.contains("ov")) return;
    e.target.classList.toggle("changed", Number(e.target.value) !== Number(e.target.dataset.orig));
    noteOverrides();
    setStatus("Данные изменены, нажмите «Посчитать»", "wait");
  });
  $("btn-reset-data").onclick = () => {
    applyOverrides({});
    calc();
  };
  noteOverrides();
}

function applyOverrides(over) {
  document.querySelectorAll("input.ov").forEach((i) => {
    const v = over?.[i.dataset.kind]?.[i.dataset.id]?.[i.dataset.field];
    i.value = v ?? i.dataset.orig;
    i.classList.toggle("changed", Number(i.value) !== Number(i.dataset.orig));
  });
  noteOverrides();
}

function readOverrides() {
  const out = {};
  document.querySelectorAll("input.ov").forEach((i) => {
    const v = i.value === "" ? NaN : Number(i.value);
    if (Number.isNaN(v) || v === Number(i.dataset.orig)) return;
    ((out[i.dataset.kind] ||= {})[i.dataset.id] ||= {})[i.dataset.field] = v;
  });
  return out;
}

function noteOverrides() {
  const n = document.querySelectorAll("input.ov.changed").length;
  $("overrides-note").textContent = n ? `изменено значений: ${n}, правки сохраняются вместе с планом` : "";
  document.querySelector('.nav a[href="#sources"]').classList.toggle("edited", n > 0);
  hints();
  initCost();
}

function request() {
  return { plan: readPlan(), overrides: readOverrides() };
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
  initCost();
  const plan = {
    plan_id: $("plan-id").value.trim() || "plan",
    scenario_id: state.scenario,
    decisions: {
      supply_orders: orders,
      capacity_reservations: reservations,
      investments,
      inventory_policy: {
        initial_stock_t: Number($("init-stock").value || 0),
        initial_stock_source_id: $("init-source").value,
        initial_stock_cost_mln: Number($("init-cost").value || 0),
        storage_id: "BASE",
      },
    },
  };
  const over = readOverrides();
  if (Object.keys(over).length) plan.data_overrides = over;
  plan.data_hash = state.inputs.data_hash;
  return plan;
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
  if (ip.initial_stock_source_id) $("init-source").value = ip.initial_stock_source_id;
  applyOverrides(plan.data_overrides || {});
  if (plan.data_hash && plan.data_hash !== state.inputs.data_hash) setStatus(`План сохранён для данных ${plan.data_hash}, сейчас загружены ${state.inputs.data_hash}`, "wait");
}

async function calc({ scrollToResults = false } = {}) {
  setStatus("Считаю…", "wait");
  try {
    const res = await api("/api/calculate", { ...request(), scenario_id: state.scenario });
    showError(null);
    render(res);
    if (scrollToResults) $("overview").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (e) {
    showError(e, { scroll: false });
    $("calc-error").textContent = $("error").textContent;
    $("calc-error").classList.remove("hidden");
  }
}

async function compare() {
  setStatus("Считаю оба сценария…", "wait");
  try {
    const cmp = await api("/api/compare", { ...request(), scenarios: ["BASE", "MANDATORY_STRESS"] });
    showError(null);
    const ids = cmp.scenarios;
    const primary = ["pv_total_mln", "total_cost_mln", "capex_total_mln", "shortage_total_t", "min_service_level_critical"];
    const formatMetric = (metric, value) => metric.startsWith("min_service") ? pct(value) : num(value, METRICS[metric][1]);
    $("compare-summary").innerHTML = ids.map((id) => `<article class="scenario-card"><h3>${esc(scenarioName(id))}</h3><p class="scenario-status ${cmp.feasible[id] ? "ok" : "bad"}">${cmp.feasible[id] ? "План исполним" : "План не исполним"}</p><dl>${primary.map((metric) => {
      const row = cmp.totals.find((r) => r.metric === metric);
      return `<div><dt>${METRICS[metric][0]}</dt><dd class="${metric === "shortage_total_t" && row?.[id] > 0 ? "deficit" : ""}">${formatMetric(metric, row?.[id])}</dd></div>`;
    }).join("")}</dl></article>`).join("");
    const differences = cmp.totals.filter((r) => primary.includes(r.metric) && typeof r["delta:" + ids[1]] === "number" && r["delta:" + ids[1]] !== 0);
    $("compare-delta").innerHTML = `<b>Изменение в стрессе относительно стандартного</b><p>${differences.length ? differences.map((r) => {
      const delta = r["delta:" + ids[1]];
      const value = r.metric.startsWith("min_service") ? `${num(delta * 100)} п. п.` : formatMetric(r.metric, delta);
      return `${METRICS[r.metric][0]}: ${delta > 0 ? "+" : ""}${value}`;
    }).join(" · ") : "Ключевые показатели совпадают"}</p>`;
    const rows = [["Исполним", ...ids.map((s) => (cmp.feasible[s] ? "да" : "нет")), ""]];
    cmp.totals.filter((r) => METRICS[r.metric]).forEach((r) => {
      const [label, d] = METRICS[r.metric];
      const f = r.metric.startsWith("min_service") ? pct : (v) => num(v, d);
      const delta = r["delta:" + ids[1]];
      rows.push([label, ...ids.map((s) => f(r[s])), r.metric.startsWith("min_service") ? `${num(delta * 100)} п. п.` : f(delta)]);
    });
    cmp.yearly.filter((r) => r.metric === "shortage_total_t").forEach((r) => rows.push([`Дефицит ${r.year}, т`, ...ids.map((s) => num(r[s])), num(r["delta:" + ids[1]])]));
    cmp.yearly.filter((r) => r.metric === "reserve_equivalent_days").forEach((r) => rows.push([`Резерв ${r.year}, дней`, ...ids.map((s) => num(Math.min(r[s], 999), 0)), ""]));
    table($("compare-table"), ["~Показатель", ...ids.map(scenarioName), "Разница"], rows);
    $("compare").classList.remove("hidden");
    setStatus(ids.map((s) => `${scenarioName(s)}: ${cmp.feasible[s] ? "исполним" : "не исполним"}`).join(" · "), ids.every((s) => cmp.feasible[s]) ? "ok" : "bad");
    $("compare").scrollIntoView({ block: "start" });
  } catch (e) { showError(e); }
}

function renderPlanList(plans, selected) {
  $("plan-list").innerHTML = plans.map((p) => `<option value="${esc(p.file.replace(/\.json$/, ""))}" ${p.plan_id === selected ? "selected" : ""}>${esc(p.plan_id)}</option>`).join("");
}

async function save() {
  try {
    const r = await api("/api/plans", request());
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
    await loadPlan(plan);
  } catch (e) { showError(e); }
}

async function loadPlan(plan) {
  // Validate the original before the editor can omit unknown channels or years.
  setStatus("Считаю…", "wait");
  const scenario = plan.scenario_id || state.scenario;
  const res = await api("/api/calculate", { plan, scenario_id: scenario, overrides: readOverrides() });
  fillForm(plan);
  showError(null);
  render(res);
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
  try {
    await loadPlan(plan);
  } catch (e) { showError(e); }
  ev.target.value = "";
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
    const res = await api(`/api/export?format=${format}&scenario=${encodeURIComponent(state.scenario)}`, request(), true);
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
    const shown = sections.filter((s) => !s.classList.contains("hidden"));
    const line = window.scrollY + 120;
    const atBottom = window.scrollY + window.innerHeight >= document.documentElement.scrollHeight - 2;
    let current = shown[0];
    shown.forEach((s) => { if (s.offsetTop <= line) current = s; });
    if (atBottom) current = shown[shown.length - 1];
    links.forEach((a) => a.classList.toggle("active", a.getAttribute("href") === "#" + current.id));
  };
  window.addEventListener("scroll", mark, { passive: true });
  mark();
  $("nav-compare").addEventListener("click", (e) => { if ($("compare").classList.contains("hidden")) { e.preventDefault(); compare(); } });
}

async function init() {
  $("btn-calc").onclick = () => calc({ scrollToResults: true });
  $("btn-calc-2").onclick = () => calc({ scrollToResults: true });
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
  const first = ["v3-earth", "base-v1"].find((id) => state.inputs.plans.some((p) => p.plan_id === id));
  renderPlanList(state.inputs.plans, first);
  if (first) await openPlan();
  else setStatus("Выберите план или загрузите JSON", "wait");
}

init();
