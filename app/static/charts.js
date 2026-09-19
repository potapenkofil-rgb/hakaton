/* Small native SVG chart components. Only display aggregation and geometry. */
const chartState={hiddenBalance:new Set(),hiddenSources:new Set(),from:null,to:null};
const balanceSeries=[['delivered_actual_t','Поставки','#2474ee'],['demand_total_t','Спрос','#71a9f8'],['closing_stock_t','Остаток','#bed7ff']];
function resetChartFilters(res){
  const years=res.yearly_balance.map(r=>r.year);chartState.from=years[0];chartState.to=years.at(-1);
  for(const id of ['chart-from','chart-to'])$(id).innerHTML=years.map(y=>`<option value="${y}">${y}</option>`).join('');
  $('chart-from').value=chartState.from;$('chart-to').value=chartState.to;
}
function chartFrame(rows,max){
  const w=620,h=245,left=53,right=17,top=18,bottom=35;
  const x=i=>left+(i+.5)*(w-left-right)/Math.max(1,rows.length);
  const y=v=>h-bottom-v/Math.max(1,max)*(h-top-bottom);
  const grid=Array.from({length:5},(_,i)=>{const v=Math.max(1,max)*i/4;return `<line x1="${left}" x2="${w-right}" y1="${y(v)}" y2="${y(v)}" class="gridline"/><text x="${left-9}" y="${y(v)+4}" text-anchor="end">${fmt(v,0)}</text>`;}).join('');
  const labels=rows.map((r,i)=>`<text x="${x(i)}" y="${h-10}" text-anchor="middle">${r.year}</text>`).join('');
  return {x,y,baseline:h-bottom,wrap:(body,title)=>`<svg viewBox="0 0 ${w} ${h}" role="group" aria-label="${title}">${grid}${body}${labels}</svg>`};
}
function pointTip(text){return `tabindex="0" data-tip="${esc(text)}" aria-label="${esc(text)}"`;}
function legend(container,series,hidden){
  container.innerHTML=series.map(([key,label,color])=>`<button type="button" data-series="${esc(key)}" aria-pressed="${!hidden.has(key)}" title="Показать или скрыть ${esc(label)}"><i style="--swatch:${color}"></i>${esc(label)}</button>`).join('');
  container.querySelectorAll('button').forEach(b=>b.onclick=()=>{const key=b.dataset.series;hidden.has(key)?hidden.delete(key):hidden.add(key);renderCharts(state.result);container.querySelector(`[data-series="${CSS.escape(key)}"]`)?.focus();});
}
function renderCharts(res){
  if(!res)return;
  const rows=res.yearly_balance.filter(r=>r.year>=chartState.from&&r.year<=chartState.to);
  const visible=balanceSeries.filter(([key])=>!chartState.hiddenBalance.has(key));
  const frame=chartFrame(rows,Math.max(1,...rows.flatMap(r=>visible.map(([key])=>r[key]))));
  let marks='';
  for(const [key,label,color] of visible){
    if(key==='closing_stock_t') marks+=rows.map((r,i)=>`<rect x="${frame.x(i)-16}" y="${frame.y(r[key])}" width="32" height="${Math.max(0,frame.baseline-frame.y(r[key]))}" fill="${color}" ${pointTip(`${r.year} · ${label}: ${fmt(r[key])} т`)}/>`).join('');
    else marks+=`<polyline points="${rows.map((r,i)=>`${frame.x(i)},${frame.y(r[key])}`).join(' ')}" fill="none" stroke="${color}" stroke-width="2.5" ${key==='demand_total_t'?'stroke-dasharray="6 5"':''}/>`+rows.map((r,i)=>`<circle cx="${frame.x(i)}" cy="${frame.y(r[key])}" r="5" fill="${color}" ${pointTip(`${r.year} · ${label}: ${fmt(r[key])} т`)}/>`).join('');
  }
  $('balance-chart').innerHTML=frame.wrap(marks,'Поставки, спрос и остаток в тоннах')+(!visible.length?'<p class="hint">Все серии скрыты. Включите их в легенде.</p>':'');
  legend($('balance-legend'),balanceSeries,chartState.hiddenBalance);
  const sources=state.inputs.sources, shown=sources.filter(s=>!chartState.hiddenSources.has(s.id));
  const values=rows.map(r=>shown.map(s=>res.source_schedule.filter(v=>v.year===r.year&&v.source_id===s.id).reduce((n,v)=>n+v.delivered_actual_t,0)));
  const stack=chartFrame(rows,Math.max(1,...values.map(v=>v.reduce((a,b)=>a+b,0))));
  $('source-chart').innerHTML=stack.wrap(values.map((volumes,i)=>{let total=0;return volumes.map((v,j)=>{const base=total;total+=v;const s=shown[j],color=sourceColors[sources.indexOf(s)%sourceColors.length];return `<rect x="${stack.x(i)-22}" y="${stack.y(total)}" width="44" height="${Math.max(0,stack.y(base)-stack.y(total))}" fill="${color}" ${pointTip(`${rows[i].year} · ${s.name}: ${fmt(v)} т`)}/>`;}).join('');}).join(''),'Структура фактических поставок по источникам')+(!shown.length?'<p class="hint">Все источники скрыты. Включите их в легенде.</p>':'');
  legend($('source-legend'),sources.map((s,i)=>[s.id,s.name,sourceColors[i%sourceColors.length]]),chartState.hiddenSources);
  $('chart-tooltip').classList.add('hidden');
}
function tooltip(target,event){
  const box=$('chart-tooltip');if(!target?.dataset.tip){box.classList.add('hidden');return;}
  box.textContent=target.dataset.tip;box.classList.remove('hidden');
  const rect=target.getBoundingClientRect();const x=event?.clientX??rect.x+rect.width/2,y=event?.clientY??rect.y;
  box.style.left=Math.max(8,Math.min(innerWidth-box.offsetWidth-8,x+12))+'px';box.style.top=Math.max(8,Math.min(innerHeight-box.offsetHeight-8,y-box.offsetHeight-12))+'px';
}
document.addEventListener('pointerover',e=>tooltip(e.target.closest('[data-tip]'),e));
document.addEventListener('pointermove',e=>{if(e.target.closest('[data-tip]'))tooltip(e.target.closest('[data-tip]'),e);});
document.addEventListener('focusin',e=>tooltip(e.target.closest('[data-tip]')));
document.addEventListener('focusout',()=>$('chart-tooltip').classList.add('hidden'));
let tooltipFrame=0;
window.addEventListener('scroll',()=>{
  if(tooltipFrame)return;
  tooltipFrame=requestAnimationFrame(()=>{tooltipFrame=0;const target=document.querySelector('[data-tip]:hover')||(document.activeElement?.matches('[data-tip]')?document.activeElement:null);tooltip(target);});
},true);
for(const id of ['chart-from','chart-to'])document.getElementById(id).addEventListener('change',()=>{
  chartState.from=Number($('chart-from').value);chartState.to=Number($('chart-to').value);
  if(chartState.from>chartState.to){if(id==='chart-from')chartState.to=chartState.from;else chartState.from=chartState.to;}
  $('chart-from').value=chartState.from;$('chart-to').value=chartState.to;renderCharts(state.result);
});
