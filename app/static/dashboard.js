/* Presentation only: all business metrics come from the calculation response. */
const esc = (v) => String(v ?? '—').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const sourceColors = ['#2862bc', '#438df1', '#91bffd', '#38b993', '#a1aec4'];
function renderDashboard(res) {
  const rows = res.yearly_balance, t = res.totals;
  const sum = key => rows.reduce((n, r) => n + r[key], 0);
  const final = rows.at(-1);
  const cards = [
    ['layers', 'Суммарные поставки', sum('delivered_actual_t'), 'т', 'Фактически за весь период'],
    ['chart', 'Суммарный спрос', sum('demand_total_t'), 'т', 'С учётом выбранного сценария'],
    ['database', 'Остаток топлива', final?.closing_stock_t, 'т', `На конец ${final?.year ?? '—'} года`],
    ['warning', 'Суммарный дефицит', t.shortage_total_t, 'т', 'Необслуженный спрос'],
    ['trend', 'Стоимость выданной тонны', t.cost_per_served_t_mln, 'млн/т', 'Млн условных единиц за тонну'],
  ];
  $('kpis').innerHTML = cards.map(([symbol,label,value,unit,note]) => `<article class="kpi"><span class="kpi-icon">${icon(symbol)}</span><div><h3>${label}</h3><strong>${fmt(value, unit === 'млн/т' ? 2 : 1)} <small>${unit}</small></strong><p>${note}</p></div></article>`).join('');
  $('period-label').textContent = rows.length ? `${rows[0].year} — ${final.year}` : 'Нет данных';
  const money = new Map(res.financial_breakdown.map(r => [r.year,r]));
  table($('year-summary'), ['Год','Поставки,<br>т','Спрос,<br>т','Остаток,<br>т','Дефицит,<br>т','Затраты,<br>млн'], rows.map(r => [r.year,fmt(r.delivered_actual_t),fmt(r.demand_total_t),fmt(r.closing_stock_t),fmt(r.shortage_total_t),fmt(money.get(r.year)?.total_mln)]), (_,i) => rows[i].shortage_total_t > 0 ? 'shortage' : '');
  renderCharts(res);
  $('structure-summary').innerHTML=[['Инвестиции CAPEX',`${fmt(t.capex_total_mln)} млн`],['Приведённые затраты PV',`${fmt(t.pv_total_mln)} млн`],['Минимальная обеспеченность критического спроса',pct(t.min_service_level_critical)]].map(([k,v])=>`<div><span>${k}</span><strong>${v}</strong></div>`).join('');
  const ip=res.meta?.plan?.decisions?.inventory_policy || readPlan().decisions.inventory_policy;
  const assumptions=[`Начальный запас: ${fmt(ip.initial_stock_t)} т; хранилище: ${ip.storage_id}.`, `Ставка дисконтирования: ${pct(t.discount_rate)}; базовый год: ${t.discount_base_year ?? '—'}.`];
  const list=values=>`<ul>${values.map(v=>`<li>${esc(v)}</li>`).join('')}</ul>`;
  $('insight-content').innerHTML=`<div class="insight"><span>${icon("file")}</span><div><h3>Ключевые допущения</h3>${list(assumptions)}</div></div><div class="insight"><span>${icon("chart")}</span><div><h3>Обслуживание спроса и затраты</h3>${list([`Обслужено ${fmt(t.served_total_t)} т; дефицит ${fmt(t.shortage_total_t)} т.`,`Общие затраты: ${fmt(t.total_cost_mln)} млн усл. ед.`])}</div></div>`;

}
