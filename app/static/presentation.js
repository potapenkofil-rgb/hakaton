/* Presentation only: feasibility always comes from the backend boolean. */
function scenarioName(id){return ({BASE:'Базовый сценарий',MANDATORY_STRESS:'Обязательный стресс-сценарий'})[id]||id;}
function scenarioLabel(id){return `${scenarioName(id)} · ${id}`;}
function criticalText(n){if(n===0)return 'Критических нарушений нет';const last=n%10,teen=n%100;return `${n} ${last===1&&teen!==11?'критическое нарушение':last>=2&&last<=4&&(teen<12||teen>14)?'критических нарушения':'критических нарушений'}`;}
function feasibilityModel(result){
  const count=(result?.constraint_checks||[]).filter(c=>c.ok===false&&c.severity==='hard').length;
  const warningCount=(result?.warnings||[]).length+(result?.constraint_checks||[]).filter(c=>c.ok===false&&['warning','soft'].includes(c.severity)).length;
  if(result?.feasible===true)return {tone:'success',title:'План исполним',count,warningCount};
  if(result?.feasible===false)return {tone:'danger',title:'План неисполним',count,warningCount};
  return {tone:'neutral',title:'Расчёт ещё не выполнен',count:0,warningCount:0};
}
function warningEntries(result){
  const messages=(result?.warnings||[]).map(raw=>{
    let m=raw.match(/^(\d{4}): бронь ([\d.,]+) т у (.+) не действует, канал недоступен$/);
    if(m)return {message:`Забронировано ${m[2]} т у ${m[3]}, но канал ещё недоступен. Бронь не действует.`,context:`Источник: ${m[3]} · ${m[1]} год`};
    m=raw.match(/^(\d{4}): (.+) доступен (\d+) мес из 12, заказ ([\d.,]+) т распределён по ним$/);
    if(m)return {message:`Источник доступен ${m[3]} мес. из 12. Заказ ${m[4]} т распределён по этим месяцам.`,context:`Источник: ${m[2]} · ${m[1]} год`};
    return {message:raw,context:''};
  });
  return messages.concat((result?.constraint_checks||[]).filter(c=>c.ok===false&&['warning','soft'].includes(c.severity)).map(c=>({message:c.reason||ruleName(c.rule_id),context:[c.source_id?`Источник: ${c.source_id}`:'',c.year?`${c.year} год`:''].filter(Boolean).join(' · ')})));
}
function warningListHTML(result){return `<ul class="warning-list">${warningEntries(result).map(w=>`<li><p>${esc(w.message)}</p>${w.context?`<small>${esc(w.context)}</small>`:''}</li>`).join('')}</ul>`;}
function planStatusHTML(result,{link='#sec-violations',showScenario=false}={}){
  const status=feasibilityModel(result);
  return `<div class="plan-status ${status.tone}" data-feasible="${result?.feasible??'unknown'}">${showScenario?`<div class="status-scenario"><b>${esc(result?.scenario_id||'')}</b><span>${esc(scenarioName(result?.scenario_id||''))}</span></div>`:'<span class="status-caption">Статус плана</span>'}<div class="feasibility-main"><span class="status-dot"></span><strong>${status.title}</strong></div><p>${status.tone==='neutral'?'Заполните данные, проверьте их и запустите расчёт.':criticalText(status.count)}</p>${status.warningCount?`<details class="warning-details"><summary class="warning-tag">Предупреждения: ${status.warningCount} · Подробнее</summary>${warningListHTML(result)}<p>Предупреждения сами по себе не делают план неисполнимым.</p></details>`:''}${status.count&&link?`<a class="status-link" href="${link}">Посмотреть нарушения →</a>`:''}</div>`;
}
const ruleNames={CAPACITY_EXCEEDED:'Превышена мощность канала',ORDER_EXCEEDS_RESERVATION:'Заказ превышает забронированную мощность',RESERVE_45D:'Недостаточный резерв топлива',CAPEX_2037:'Превышен лимит инвестиций (CAPEX) к 2037 году',CAPEX_2040:'Превышен лимит инвестиций (CAPEX) к 2040 году',BASE_CRITICAL_SERVICE:'Недостаточно топлива для критического спроса',BASE_TOTAL_SERVICE:'Спрос обеспечен не полностью',SOURCE_UNAVAILABLE:'Источник поставок ещё недоступен',STORAGE_CAPACITY:'Превышена вместимость хранилища',ISRU_FINANCING:'Не выполнены условия финансирования лунного производства',INVESTMENT_NOT_AVAILABLE:'Инвестиция пока недоступна',EMERGENCY_BASE_STREAK:'Аварийный канал используется слишком долго',STRESS_LOSS_LIMIT:'Превышены допустимые потери топлива'};
function ruleName(id){return ruleNames[id]||'Ограничение плана';}
function checkValue(value,check){
  if(value===null||value===undefined)return '—';
  if(check.unit==='share')return pct(value);
  const unit=({t:'т',days:'дн.',years:'лет',months:'мес.','т':'т','млн':'млн усл. ед.',mln:'млн усл. ед.',mln_units:'млн усл. ед.'})[check.unit]||'';
  return `${fmt(value,2)} ${unit}`.trim();
}
function violationHTML(c){
  return `<article class="violation-card"><h3 title="${esc(c.rule_id)}">${esc(ruleName(c.rule_id))}</h3><p class="hint">${esc(c.year??'Весь период')}${c.source_id?` · Источник ${esc(c.source_id)}`:''}</p><dl><div><dt>Фактически</dt><dd>${esc(checkValue(c.actual,c))}</dd></div><div><dt>Допустимо</dt><dd>${esc(c.operator)} ${esc(checkValue(c.limit,c))}</dd></div><div><dt>${c.operator?.includes('>')?'Недостаток':'Превышение'}</dt><dd>${esc(checkValue(c.excess,c))}</dd></div></dl><p>${esc(c.reason||'Проверьте параметры плана.')}</p></article>`;
}
function shortViolationsHTML(res){
  const hard=res.constraint_checks.filter(c=>!c.ok&&c.severity==='hard');
  return hard.length?`<div class="violation-grid">${hard.map(violationHTML).join('')}</div>`:'<p class="quiet-success">Критических нарушений нет.</p>';
}
function renderRiskGroups(res){
  const checks=res.constraint_checks.filter(c=>!c.ok),hard=checks.filter(c=>c.severity==='hard'),info=checks.filter(c=>c.severity==='info');
  const warnings=warningEntries(res);
  $('critical-issues').innerHTML=hard.length?hard.map(violationHTML).join(''):'<p class="quiet-success">Критических нарушений нет.</p>';
  $('warning-issues').innerHTML=warnings.length?warningListHTML(res):'<p>Предупреждений нет.</p>';
  $('violations').closest('details').hidden=checks.length===0;
  $('information-issues').innerHTML=info.length?`<p>Справочные проверки не влияют на исполнимость этого сценария.</p>${info.map(c=>`<p><b>${esc(c.year)} · ${esc(ruleName(c.rule_id))}</b><br>${esc(c.reason)}</p>`).join('')}`:'<p>Дополнительных пояснений нет.</p>';
}
const metricNames={pv_per_served_t_mln:'Приведённая стоимость тонны, млн усл. ед./т',total_cost_mln:'Общие затраты, млн усл. ед.',pv_total_mln:'Приведённые затраты (PV), млн усл. ед.',capex_total_mln:'Инвестиции (CAPEX), млн усл. ед.',served_total_t:'Обслуженный спрос, т',shortage_total_t:'Дефицит, т',cost_per_served_t_mln:'Стоимость выданной тонны, млн усл. ед./т',min_service_level_total:'Минимальная обеспеченность спроса, %',min_service_level_critical:'Минимальная обеспеченность критического спроса, %',demand_total_t:'Спрос, т',demand_critical_t:'Критический спрос, т',delivered_actual_t:'Фактические поставки, т',losses_t:'Потери топлива, т',shortage_critical_t:'Дефицит критического спроса, т',service_level_total:'Обеспеченность спроса, %',service_level_critical:'Обеспеченность критического спроса, %',opening_stock_t:'Начальный запас, т',closing_stock_t:'Конечный остаток, т',reserve_equivalent_days:'Резерв, дн.',procurement_mln:'Закупка топлива, млн усл. ед.',reservation_mln:'Бронирование, млн усл. ед.',holding_mln:'Хранение, млн усл. ед.',fixed_opex_mln:'Постоянные расходы, млн усл. ед.',capex_mln:'Инвестиции за год, млн усл. ед.',total_mln:'Затраты за год, млн усл. ед.',pv_mln:'Приведённые затраты за год, млн усл. ед.',discount_rate:'Ставка дисконтирования, %',discount_base_year:'Базовый год дисконтирования',initial_stock_mln:'Стоимость начального запаса, млн усл. ед.',take_or_pay_topup_mln:'Доплата за минимальный объём, млн усл. ед.'};
function metricLabel(key){return metricNames[key]||'Дополнительный показатель';}
function metricNumber(value,key,delta=false){
  if(typeof value!=='number'||!Number.isFinite(value))return '—';
  const isShare=key.includes('service_level')||key==='discount_rate';
  const n=isShare?value*100:value, digits=['hard_count','discount_base_year'].includes(key)?0:1;
  const rounded=Number(n.toFixed(digits));
  if(delta&&rounded===0)return '0';
  const unit=isShare?'п.п.':key.endsWith('_t_mln')?'млн/т':key.endsWith('_mln')?'млн':key.endsWith('_t')?'т':key.endsWith('_days')?'дн.':'';
  return (delta&&rounded!==0?(rounded>0?'+':'−'):'')+fmt(delta?Math.abs(n):n,digits)+(delta&&unit?' '+unit:'');
}
function comparisonTable(el,head,rows,yearly=false){
  el.classList.add('comparison-table');el.classList.toggle('by-year',yearly);
  el.innerHTML='<thead><tr>'+head.map((h,i)=>`<th scope="col" class="${i===(yearly?1:0)?'metric':'number'}">${h}</th>`).join('')+'</tr></thead><tbody>'+rows.map(row=>'<tr>'+row.map((cell,i)=>`<td class="${i===(yearly?1:0)?'metric':'number'}"${String(cell).includes('(PV)')?' title="PV — текущая стоимость будущих расходов с учётом дисконтирования."':''}>${esc(cell)}</td>`).join('')+'</tr>').join('')+'</tbody>';
}
function humanInputError(error,plan){
  const path=error.path||'', raw=error.message||'Проверьте введённое значение.';
  let context='', message=raw;
  const match=path.match(/(supply_orders|capacity_reservations)\[(\d+)\]/);
  const row=match&&plan?.decisions?.[match[1]]?.[Number(match[2])];
  if(row)context=`Источник ${row.source_id??'не выбран'} · ${row.year??'год не задан'}`;
  else if(path.includes('inventory_policy'))context='Начальный запас и хранилище';
  else if(path.includes('investments'))context='Инвестиции';
  else context=({plan_id:'Название и номер плана',scenario_id:'Расчётный сценарий','raw-plan':'Исходный JSON'})[path]||'';
  if(/negative|отриц|неотрицательное/i.test(raw)){
    const label=path.includes('reserved_capacity_t')?'Забронированный объём':path.includes('cost')?'Стоимость начального запаса':path.includes('initial_stock_t')?'Начальный запас':'Объём поставки';
    message=`${label} должен быть числом не меньше нуля.`;
  }
  return {message,context,original:message!==raw?raw:''};
}
if(typeof module!=='undefined')module.exports={feasibilityModel,criticalText,scenarioName,ruleName,humanInputError,warningEntries,metricNumber};
function renderResultSummary(res){
  $('result-plan-status').innerHTML=planStatusHTML(res);
  $('report-plan-status').innerHTML=planStatusHTML(res,{showScenario:true,link:null});
  $('export-plan-status').innerHTML=planStatusHTML(res,{link:null});
  const t=res.totals,summary=[['Общие затраты',`${fmt(t.total_cost_mln)} млн`],['Приведённые затраты (PV)',`${fmt(t.pv_total_mln)} млн`],['Инвестиции (CAPEX)',`${fmt(t.capex_total_mln)} млн`],['Дефицит',`${fmt(t.shortage_total_t)} т`]];
  const cards=rows=>rows.map(([label,value])=>`<div><span>${esc(label)}</span><strong>${esc(value)}</strong></div>`).join('');
  $('report-kpis').innerHTML=cards(summary);$('cost-summary').innerHTML=cards(summary.slice(0,3));
  $('report-issues').innerHTML=shortViolationsHTML(res);
  const sources=new Set(res.source_schedule.filter(s=>s.ordered_t>0||s.reserved_capacity_t>0).map(s=>s.source_id));
  $('logistics-summary').textContent=`Источников в плане: ${sources.size}. Сроки доступности и размещения заказов приведены ниже по годам.`;
}
function resetComparison(){
  $('comparison-details').hidden=true;
  $('sec-compare').classList.add('hidden');$('compare-loading').classList.add('hidden');$('compare-placeholder').classList.remove('hidden');
  $('compare-placeholder').innerHTML='<p>Сравнение ещё не выполнено.</p><p class="hint">Нажмите «Сравнить», чтобы увидеть исполнимость, затраты и дефицит в обоих сценариях.</p>';
  document.querySelector('.comparison-slot').setAttribute('aria-busy','false');
  for(const id of ['comparison-statuses','compare-summary','compare-totals','compare-yearly'])$(id).replaceChildren();
}
function renderComparison(cmp){
  $('comparison-details').hidden=false;
  const ids=cmp.scenarios;
  $('comparison-statuses').innerHTML=ids.map(id=>{
    const result={...cmp.results[id],scenario_id:id,feasible:cmp.feasible[id]};
    return `<div>${planStatusHTML(result,{showScenario:true,link:null})}${feasibilityModel(result).count?`<details class="comparison-issues"><summary>Посмотреть нарушения</summary>${(result.constraint_checks||[]).filter(c=>!c.ok&&c.severity==='hard').map(violationHTML).join('')}</details>`:''}</div>`;
  }).join('');
  const head=['Показатель',...ids.map(id=>`${esc(id)}<br>${esc(scenarioName(id))}`),'Разница STRESS − BASE'];
  const keys=['total_cost_mln','pv_total_mln','capex_total_mln','delivered_actual_t','shortage_total_t','min_service_level_total','hard_count'];
  const value=(id,key)=>key==='hard_count'?feasibilityModel(cmp.results[id]).count:key==='delivered_actual_t'?cmp.results[id].yearly_balance.reduce((n,r)=>n+r.delivered_actual_t,0):cmp.results[id].totals[key];
  comparisonTable($('compare-summary'),head,keys.map(key=>{
    const values=ids.map(id=>value(id,key));const diff=values.every(v=>typeof v==='number')?values[1]-values[0]:null;
    return [key==='hard_count'?'Критические нарушения':metricLabel(key),...values.map(v=>metricNumber(v,key)),metricNumber(diff,key,true)];
  }));
  comparisonTable($('compare-totals'),head,cmp.totals.map(r=>[metricLabel(r.metric),...ids.map(id=>metricNumber(r[id],r.metric)),metricNumber(r['delta:'+ids[1]],r.metric,true)]));
  comparisonTable($('compare-yearly'),['Год',...head],cmp.yearly.map(r=>[r.year,metricLabel(r.metric),...ids.map(id=>metricNumber(r[id],r.metric)),metricNumber(r['delta:'+ids[1]],r.metric,true)]),true);
  $('compare-placeholder').classList.add('hidden');$('sec-compare').classList.remove('hidden');
}
