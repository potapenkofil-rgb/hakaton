/* Workflow state lives in state.plan. Forms are projections; results are valid
   only for the revision explicitly checked and sent to the real calculation API. */
const icons={
 clock:'<circle cx="12" cy="12" r="9"/><path d="M12 6v6l4 2"/>',home:'<path d="m3 11 9-8 9 8M5 10v11h5v-7h4v7h5V10"/>',grid:'<rect x="3" y="3" width="6" height="6" rx="1"/><rect x="15" y="3" width="6" height="6" rx="1"/><rect x="3" y="15" width="6" height="6" rx="1"/><rect x="15" y="15" width="6" height="6" rx="1"/>',layers:'<path d="m3 7 9-4 9 4-9 4ZM3 12l9 4 9-4M3 17l9 4 9-4"/>',rocket:'<path d="M14 4c3-2 7-1 7-1s1 4-1 7l-8 8-6-6ZM6 12l-3 1 1-5 6-1M12 18l-1 3 5-1 1-6M4 17l-2 5 5-2"/><circle cx="16" cy="8" r="2"/>',chart:'<path d="M4 21V13h4v8M10 21V8h4v13M16 21V3h4v18"/>',warning:'<path d="m12 3 10 18H2ZM12 9v5m0 3v1"/>',file:'<path d="M5 2h9l5 5v15H5ZM14 2v6h5M8 12h8M8 16h8"/>',search:'<circle cx="10" cy="10" r="7"/><path d="m15 15 6 6"/>',database:'<ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v14c0 4 16 4 16 0V5M4 10c0 4 16 4 16 0M4 15c0 4 16 4 16 0"/>',edit:'<path d="m4 16 12-12 4 4L8 20l-5 1ZM14 6l4 4"/>',folder:'<path d="M3 7V4h6l2 3h10v14H3ZM3 11h18"/>',refresh:'<path d="M20 8a8 8 0 0 0-14-3L3 8m0-5v5h5M4 16a8 8 0 0 0 14 3l3-3m0 5v-5h-5"/>',settings:'<path d="m9 3-1 3-3 1 1 3-2 2 2 2-1 3 3 1 1 3h6l1-3 3-1-1-3 2-2-2-2 1-3-3-1-1-3Z"/><circle cx="12" cy="12" r="3"/>',save:'<path d="M3 3h15l3 3v15H3ZM7 3v6h10V3M7 21v-8h10v8"/>',trend:'<path d="m2 18 6-7 5 4 9-12"/>',calendar:'<rect x="3" y="5" width="18" height="17" rx="2"/><path d="M7 2v6M17 2v6M3 11h18M7 15h2m3 0h2m3 0h1M7 18h2m3 0h2"/>'
};
const icon=name=>`<svg class="ui-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${icons[name]||icons.file}</svg>`;
function mountIcons(){document.querySelectorAll('[data-icon]').forEach(el=>{if(!el.querySelector('.ui-icon'))el.insertAdjacentHTML('afterbegin',icon(el.dataset.icon));});}
function currentValidation(){
  const v=validatePlan(state.plan,state.inputs);
  if(state.rawDirty)v.errors.unshift({path:'raw-plan',message:'JSON изменён, но ещё не применён. Нажмите «Применить JSON».'});
  document.querySelectorAll('#form-content input[type=number]').forEach(el=>{if(el.validity.badInput)v.errors.push({path:el.title||el.id,message:'Введите корректное число.'});});
  return v;
}
function readPlan(){return state.plan ? structuredClone(state.plan) : null;}
function busy(){return ['LOADING','CALCULATING'].includes(state.phase);}
function showError(err){
  $('error').classList.toggle('hidden',!err);
  if(!err){$('error').textContent='';return;}
  state.phase=err.error==='INVALID_PLAN'?'VALIDATION ERROR':'ERROR';
  $('error').dataset.error=err.error||'ERROR';
  $('error').textContent=err.error==='INVALID_PLAN' ? 'План не принят. Исправьте данные:\n'+(err.details||[]).map(e=>{const h=humanInputError(e,state.plan);return `${h.message}${h.context?' · '+h.context:''}${h.original?' ('+h.original+')':''}`;}).join('\n') : (err.message||'Не удалось выполнить действие. Повторите попытку.');
  setStatus('Действие не выполнено. Данные сохранены в текущем черновике.','bad');
  updateUI();
}
function invalidate(){
  state.revision++;state.request++;state.validatedRevision=-1;state.validation=null;state.result=null;state.comparison=null;state.step=1;state.phase=state.plan?'DRAFT':'EMPTY';
  resetComparison();$('chart-tooltip').classList.add('hidden');
}
function newPlan(){return {plan_id:`scenario-${Date.now()}`,label:'',scenario_id:state.inputs.scenarios[0]?.scenario_id||'BASE',decisions:{supply_orders:[],capacity_reservations:[],investments:[],inventory_policy:{storage_id:'BASE'}}};}
function reset(){
  state.plan=null;state.source='';state.rawMode=false;state.rawDirty=false;invalidate();
  fillForm({decisions:{}});$('plan-id').value='';$('raw-plan').value='';$('controls').open=false;showError(null);setStatus('');route('scenarios');updateUI();
}
function ensureDraft(){if(!state.plan){state.plan=newPlan();state.source='Ручной ввод';fillForm(state.plan);$('plan-id').value='';}}
function editScenario(){if(!state.inputs||busy())return;ensureDraft();route('modeling');$('controls').open=true;updateUI();$('controls').scrollIntoView({behavior:'smooth'});}
function scheduleCalc(){
  if(!state.inputs||state.rawMode)return;
  ensureDraft();
  const form=readForm();state.plan={...state.plan,...form};
  // A blank optional field stays absent, rather than becoming a fabricated zero.
  if($('init-stock').value==='')delete state.plan.decisions.inventory_policy.initial_stock_t;
  if($('init-cost').value==='')delete state.plan.decisions.inventory_policy.initial_stock_cost_mln;
  invalidate();showError(null);setStatus('Черновик изменён. Перейдите к проверке.');$('raw-plan').value=JSON.stringify(state.plan,null,2);updateUI();
}
function acceptPlan(plan,source){
  state.plan=plan;state.source=source;state.rawDirty=false;invalidate();
  const validation=validatePlan(plan,state.inputs);state.rawMode=validation.errors.length>0;
  $('raw-plan').value=JSON.stringify(plan,null,2);
  if(!state.rawMode)fillForm(plan);
  else {$('plan-id').value=typeof plan?.label==='string'?plan.label:typeof plan?.plan_id==='string'?plan.plan_id:'';$('controls').open=true;$('raw-panel').open=true;}
  showError(null);setStatus(state.rawMode?'JSON прочитан. Найдены ошибки: исправьте исходный JSON или откройте этап проверки.':'Данные загружены. Перейдите к проверке.',state.rawMode?'wait':'ok');route('scenarios');updateUI();
}
async function loadFile(ev){
  const file=ev.target.files[0];if(!file)return;
  const request=++state.request;state.phase='LOADING';updateUI();setStatus(`Читаю ${file.name}…`,'wait');
  try{const text=await file.text();if(request!==state.request)return;let plan;try{plan=JSON.parse(text.replace(/^\uFEFF/,''));}catch{throw {message:`Файл «${file.name}» не является корректным JSON. Проверьте синтаксис и выберите файл повторно.`};}acceptPlan(plan,`Файл: ${file.name}`);}
  catch(e){if(request===state.request)showError(e);}finally{ev.target.value='';}
}
function applyJSON(){try{acceptPlan(JSON.parse($('raw-plan').value),state.source||'Редактор JSON');}catch{showError({message:'JSON содержит синтаксическую ошибку. Исправьте её в редакторе.'});}}
function review(){
  if(busy())return;
  showError(null);state.validation=currentValidation();
  state.validatedRevision=state.validation.errors.length?-1:state.revision;
  state.phase=state.validation.errors.length?'VALIDATION ERROR':'READY';state.step=2;
  renderValidation();setStatus(state.validation.errors.length?'Исправьте критические ошибки перед расчётом.':'Формат данных проверен. Можно запускать расчёт.',state.validation.errors.length?'bad':'ok');route('validation');
}
function renderValidation(){
  const v=state.validation;if(!v)return;
  $('validation-results').innerHTML=[['errors','Критические ошибки','bad'],['warnings','Предупреждения','warn'],['passed','Успешно проверено','good']].map(([key,title,cls])=>`<div class="validation-column ${cls}"><h3>${title} <span>${v[key].length}</span></h3>${v[key].length?'<ul>'+v[key].map(e=>`<li><p>${esc(humanInputError(e,state.plan).message)}</p><small>${esc(humanInputError(e,state.plan).context)}</small>${humanInputError(e,state.plan).original?`<details><summary>Пояснение проверки</summary>${esc(e.message)}</details>`:''}${key==='errors'?`<button class="text-button" data-fix="${esc(e.path)}">Исправить →</button>`:''}</li>`).join('')+'</ul>':'<p>Нет</p>'}</div>`).join('');
}
function renderReadiness(){
  const v=state.validation||(state.plan?currentValidation():{errors:[],warnings:[],passed:[]});
  const categories=[['identity','Сценарий и исходные данные'],['supply_orders','Заказы поставок'],['capacity_reservations','Бронирование мощностей'],['investments','Инвестиции'],['inventory_policy','Запас и хранилище']];
  const category=path=>categories.find(([key])=>path?.startsWith('decisions.'+key))?.[0]||'identity';
  const known=!!state.inputs&&!!state.plan&&!state.rawDirty;
  $('readiness').innerHTML=categories.map(([key,label])=>{
    const errors=v.errors.filter(e=>category(e.path)===key).length,warnings=v.warnings.filter(e=>category(e.path)===key).length;
    const checked=known&&v.passed.some(e=>category(e.path)===key);
    const tone=errors?'bad':warnings?'warn':checked?'yes':'neutral';
    const text=errors?`Ошибок: ${errors}`:warnings?`Предупреждений: ${warnings}`:checked?'Формат корректен':'Нужны данные';
    return `<div class="readiness-row" data-category="${key}" data-tone="${tone}"><span class="check ${tone}">${({bad:'!',warn:'!',yes:'✓',neutral:''})[tone]}</span><span>${label}</span><small>${text}</small></div>`;
  }).join('')+`<p class="hint readiness-count">Ошибок: ${v.errors.length} · Предупреждений: ${v.warnings.length}. Исполнимость определяется после расчёта.</p>`;
}
function updateUI(){
  const ready=!!state.inputs, p=state.rawDirty?null:state.plan, d=p?.decisions, ip=d?.inventory_policy;
  const sources=new Set([...(Array.isArray(d?.supply_orders)?d.supply_orders:[]),...(Array.isArray(d?.capacity_reservations)?d.capacity_reservations:[])].filter(r=>r&&(r.ordered_t>0||r.reserved_capacity_t>0)&&state.inputs?.sources.some(s=>s.id===r.source_id)).map(r=>r.source_id));
  const years=ready&&p?state.inputs.years:[], period=years.length?`${years[0]} – ${years.at(-1)}`:'Не задано';
  renderReadiness();
  const label=busy()?(state.phase==='CALCULATING'?'Расчёт…':'Загрузка…'):state.result?'Рассчитан':state.validatedRevision===state.revision?'Проверен':p?'Черновик':'Расчёт не выполнен';
  const summary=[['calendar','Период',period],['clock','Длительность',years.length?`${years.length} лет`:'Не задано'],['layers','Источники поставок',sources.size?`${sources.size} источн.`:'Не задано'],['database','Начальный запас',typeof ip?.initial_stock_t==='number'?`${fmt(ip.initial_stock_t)} т`:'Не задано'],['file','Статус',label]];
  $('scenario-summary').innerHTML=summary.map(([i,k,v])=>`<div>${icon(i)}<span><small>${k}</small><strong>${esc(v)}</strong></span></div>`).join('');
  $('source-note').textContent=state.source||'Данные ещё не загружены';
  $('controls').classList.toggle('hidden',!state.plan&&!state.rawMode);
  document.querySelectorAll('[data-result]').forEach(a=>{a.setAttribute('aria-disabled',String(!state.result));a.title=state.result?'':'Доступно после расчёта';});
  document.querySelectorAll('[data-step]').forEach(b=>{const step=Number(b.dataset.step);b.disabled=busy()||!ready||(step===3)||(step>=4&&!state.result);b.classList.toggle('current',step===state.step);b.classList.toggle('complete',step<state.step);if(step===state.step)b.setAttribute('aria-current','step');else b.removeAttribute('aria-current');});
  for(const id of ['choose-json','choose-manual','choose-saved','choose-open','btn-reset','check-now','btn-validate','edit-scenario'])$(id).disabled=!ready||busy();
  $('btn-save').disabled=!p||!ready||busy();$('plan-id').disabled=!ready||busy()||state.rawMode;
  $('btn-calc').disabled=busy()||state.validatedRevision!==state.revision||!!state.validation?.errors.length;
  $('btn-calc').title=$('btn-calc').disabled?'Сначала устраните ошибки и проверьте данные.':'';
  $('form-content').querySelectorAll('input,select').forEach(el=>el.disabled=!p||busy()||state.rawMode);
  $('scenario').disabled=!p||busy()||state.rawMode;
  document.querySelectorAll('#reports-view button').forEach(el=>el.disabled=!state.result||busy());
  for(const id of ['result-scenario-select','edit-results','to-reports'])$(id).disabled=busy();
  $('apply-json').disabled=busy();$('raw-plan').disabled=busy();
}
const routes={scenarios:[1,'Сценарий'],modeling:[1,'Сценарий'],validation:[2,'Проверка данных'],calculating:[3,'Расчёт'],overview:[4,'Итоги расчёта'],'balance-detail':[4,'Поставки и запасы'],infrastructure:[4,'Инфраструктура'],logistics:[4,'Логистика и сроки'],economics:[4,'Затраты'],'sec-violations':[4,'Риски и ограничения'],comparison:[5,'Сравнение'],reports:[5,'Экспорт и отчёты']};
function route(name,scroll=true){
  if(!routes[name])name='scenarios';
  if(name==='calculating'&&state.phase!=='CALCULATING')name=state.validation?'validation':'scenarios';
  if(routes[name][0]>=4&&!state.result)name='scenarios';
  if(name==='validation'&&!state.validation){review();return;}
  if(busy()&&state.phase==='CALCULATING')name='calculating';
  state.step=routes[name][0];
  for(const [id,step] of [['input-view',1],['validation-view',2],['calculating-view',3],['results-view',4],['reports-view',5]])$(id).classList.toggle('hidden',state.step!==step);
  $('breadcrumb-current').textContent=routes[name][1];
  $('page-title').textContent=state.step===1?'Создание сценария снабжения орбитального топливного узла':routes[name][1];
  $('page-subtitle').textContent=state.step===1?'Сначала загрузите исходные данные или заполните параметры сценария. Затем проверьте корректность, выполните расчёт и перейдите к результатам.':state.step===2?'Проверьте данные перед отправкой в расчётное ядро.':state.step===3?'Расчёт выполняется на сервере. Дождитесь результата.':`${state.plan?.label||state.plan?.plan_id||''} · ${state.result?.scenario_id||state.plan?.scenario_id||''}`;
  setActiveSection(name);updateUI();observeNavigation();
  if(scroll){
    if(scroll==='instant'){navigationTarget=null;window.scrollTo({top:0,behavior:'instant'});}
    else if(state.step>=4)scrollToSection(name);
    else window.scrollTo({top:0,behavior:'instant'});
  }

}
async function calc(){
  if(busy()||state.validatedRevision!==state.revision)return;
  const plan=readPlan(),revision=state.revision,request=++state.request;
  state.phase='CALCULATING';showError(null);setStatus('Выполняется расчёт сценария…','wait');route('calculating');
  try{
    const res=await api('/api/calculate',{plan,scenario_id:plan.scenario_id});
    if(revision!==state.revision||request!==state.request)return;
    state.result=res;state.phase='SUCCESS';resetChartFilters(res);render(res);
    $('result-name').textContent=plan.label||plan.plan_id;$('result-scenario').textContent=scenarioLabel(res.scenario_id);
    $('result-scenario-select').innerHTML=$('scenario').innerHTML;$('result-scenario-select').value=res.scenario_id;
    $('report-context').textContent=`План: ${plan.label||plan.plan_id} · ${scenarioLabel(res.scenario_id)}`;
    route('overview','instant');
  }catch(e){if(request!==state.request)return;state.result=null;showError(e);if(e.error==='INVALID_PLAN'){state.validation={errors:e.details||[],warnings:[],passed:[]};state.validatedRevision=-1;renderValidation();}route('validation');}
}
async function changeResultScenario(){
  const sid=$('result-scenario-select').value;state.plan.scenario_id=sid;$('scenario').value=sid;invalidate();
  state.validation=currentValidation();state.validatedRevision=state.validation.errors.length?-1:state.revision;
  if(state.validation.errors.length){renderValidation();route('validation');}else await calc();
}
function openPicker(){if(!state.inputs||busy())return;$('open-dialog').showModal();$('plan-list').focus();}
async function open(){
  if(busy())return;
  const id=$('plan-list').value;if(!id)return;
  const request=++state.request;state.phase='LOADING';$('btn-open').disabled=true;updateUI();setStatus('Загружаю сохранённый план…','wait');
  try{const plan=await api(`/api/plans/${encodeURIComponent(id)}`);if(request!==state.request)return;$('open-dialog').close();acceptPlan(plan,`Сохранённый план: ${plan.label||plan.plan_id}`);}catch(e){if(request===state.request){$('open-dialog').close();showError(e);}}finally{$('btn-open').disabled=false;}
}
async function save(){
  const validation=currentValidation();if(validation.errors.length){review();return;}
  const revision=state.revision,plan=readPlan();state.phase='LOADING';updateUI();setStatus('Сохраняю сценарий…','wait');
  try{const r=await api('/api/plans',{plan});state.inputs.plans=r.plans;renderPlanList(r.plans,r.plan_id);if(revision===state.revision){state.phase=state.result?'SUCCESS':'DRAFT';showError(null);setStatus(`Сохранено на сервере: ${r.saved}`,'ok');updateUI();}}catch(e){showError(e);}
}
function downloadBlob(blob,name){const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000);}
function downloadPlan(){if(state.result)downloadBlob(new Blob([JSON.stringify(readPlan(),null,2)],{type:'application/json'}),`${state.plan.plan_id}.json`);}
async function exportFile(format){
  if(!state.result||busy())return;state.phase='LOADING';updateUI();setStatus('Готовлю выгрузку…','wait');
  try{const res=await api(`/api/export?format=${format}&scenario=${encodeURIComponent(state.plan.scenario_id)}`,{plan:readPlan()},true);downloadBlob(await res.blob(),(res.headers.get('Content-Disposition')||'').match(/filename="(.+)"/)?.[1]||`export.${format}`);state.phase='SUCCESS';showError(null);setStatus(`Выгрузка ${format.toUpperCase()} готова`,'ok');updateUI();}catch(e){showError(e);}
}
async function compare(){
  if(!state.result||busy())return;
  const request=++state.request,revision=state.revision;
  state.phase='LOADING';updateUI();setStatus('Сравниваем базовый и обязательный стресс-сценарий…');
  $('compare-placeholder').classList.add('hidden');$('sec-compare').classList.add('hidden');$('compare-loading').classList.remove('hidden');
  document.querySelector('.comparison-slot').setAttribute('aria-busy','true');
  try{
    const cmp=await api('/api/compare',{plan:readPlan(),scenarios:['BASE','MANDATORY_STRESS']});
    if(request!==state.request||revision!==state.revision)return;
    state.comparison=cmp;renderComparison(cmp);state.phase='SUCCESS';showError(null);
    setStatus('Сравнение выполнено. Статус каждого сценария показан отдельно.');updateUI();
  }catch(e){
    if(request!==state.request)return;
    if(state.comparison)renderComparison(state.comparison);
    else {$('compare-placeholder').classList.remove('hidden');$('compare-placeholder').textContent='Не удалось выполнить сравнение. Повторите попытку.';}
    showError(e);
  }finally{
    if(request===state.request){$('compare-loading').classList.add('hidden');document.querySelector('.comparison-slot').setAttribute('aria-busy','false');observeNavigation();}
  }
}
function search(){
  const input=$('search'), q=input.value.trim().toLocaleLowerCase('ru'), box=$('search-results');
  $('search-clear').hidden=input.value.length===0;
  box.replaceChildren();box.classList.toggle('hidden',!q);if(!q)return;
  const hits=[...document.querySelectorAll('.sidebar nav a')].filter(a=>a.textContent.toLocaleLowerCase('ru').includes(q));
  if(!hits.length){box.textContent='Раздел не найден.';return;}
  for(const hit of hits){
    const button=document.createElement('button');button.type='button';
    button.textContent=hit.textContent;button.disabled=busy()||hit.getAttribute('aria-disabled')==='true';
    if(button.disabled)button.textContent+=' · доступно после расчёта';
    button.onclick=()=>{input.value='';search();input.blur();route(hit.hash.slice(1));};
    box.append(button);
  }
}
async function init(){
  state.phase='LOADING';updateUI();$('retry-inputs').classList.add('hidden');
  try{state.inputs=await api('/api/inputs');buildEditor();renderSources();renderPlanList(state.inputs.plans);$('input-sources').innerHTML=$('sources').innerHTML;table($('input-demand'),['Год','Спрос, т','Критический спрос, т'],state.inputs.demand.map(d=>[d.year,fmt(d.total),fmt(d.critical)]));reset();}
  catch(e){showError(e);$('retry-inputs').classList.remove('hidden');}
}
mountIcons();
$('choose-json').onclick=()=>$('plan-file').click();$('plan-file').onchange=loadFile;
$('choose-manual').onclick=editScenario;$('edit-scenario').onclick=editScenario;
$('choose-saved').onclick=openPicker;$('choose-open').onclick=openPicker;
$('close-dialog').onclick=()=>$('open-dialog').close();$('btn-open').onclick=open;
$('btn-reset').onclick=reset;$('btn-save').onclick=save;$('btn-validate').onclick=review;$('check-now').onclick=review;$('btn-calc').onclick=calc;
$('back-input').onclick=()=>route('scenarios');$('edit-results').onclick=editScenario;$('to-reports').onclick=()=>route('reports');
$('apply-json').onclick=applyJSON;$('btn-compare').onclick=compare;$('btn-download').onclick=downloadPlan;$('btn-csv').onclick=()=>exportFile('csv');$('btn-xlsx').onclick=()=>exportFile('xlsx');
$('result-scenario-select').onchange=changeResultScenario;$('retry-inputs').onclick=init;
$('plan-id').addEventListener('input',()=>{const name=$('plan-id').value;ensureDraft();state.plan.label=name; $('plan-id').value=name;invalidate();showError(null);setStatus('Название изменено. Перейдите к проверке.');updateUI();});
$('raw-plan').addEventListener('input',()=>{invalidate();state.rawMode=true;state.rawDirty=true;setStatus('JSON изменён. Примените правки перед проверкой.','wait');updateUI();});
$('search').oninput=search;$('search').onclick=()=>{if($('search').value)search();};$('search-clear').onclick=()=>{$('search').value='';search();$('search').focus();};$('search').onfocus=()=>{if($('search').value)search();};
$('search').onkeydown=e=>{if(e.key==='Escape'){e.preventDefault();$('search-results').classList.add('hidden');}if(e.key==='ArrowDown'){if($('search-results').classList.contains('hidden'))search();$('search-results').querySelector('button:not(:disabled)')?.focus();e.preventDefault();}};
document.addEventListener('keydown',e=>{if(e.key==='Escape')$('search-results').classList.add('hidden');});
document.addEventListener('click',e=>{
  if(!e.target.closest('.search-box'))$('search-results').classList.add('hidden');
  const step=e.target.closest('[data-step]');if(step&&!step.disabled){const n=+step.dataset.step;if(n===2)review();else route({1:'scenarios',4:'overview',5:'reports'}[n]);}
  const fix=e.target.closest('[data-fix]');if(fix){
    editScenario();const path=fix.dataset.fix;
    let field;
    if(state.rawMode||path==='raw-plan'){$('raw-panel').open=true;field=$('raw-plan');}
    else if(path==='plan_id'||path==='plan')field=$('plan-id');
    else if(path==='scenario_id')field=$('scenario');
    else if(path.includes('inventory_policy'))field=$({'initial_stock_t':'init-stock','initial_stock_cost_mln':'init-cost','initial_stock_source_id':'init-source','storage_id':'init-storage'}[path.split('.').at(-1)]||'init-stock');
    else if(path.includes('investments'))field=$(path.includes('exercise')?'en-exercise':path.includes('financing')?'isru-on':'en-on');
    else {
      const match=path.match(/(supply_orders|capacity_reservations)\[(\d+)\]/);
      const row=match&&state.plan.decisions[match[1]][Number(match[2])];
      field=row?document.querySelector(`#editor input[data-kind="${match[1]==='supply_orders'?'order':'res'}"][data-src="${CSS.escape(row.source_id)}"][data-year="${row.year}"]`):$('editor').querySelector('input');
    }
    field?.focus();field?.scrollIntoView({block:'center',behavior:'smooth'});
  }
  const a=e.target.closest('a[href^="#"]');if(a){e.preventDefault();if(a.getAttribute('aria-disabled')==='true'||busy())return;const name=a.hash.slice(1);if(name==='modeling')editScenario();else route(name);}
});
window.addEventListener('hashchange',()=>route(location.hash.slice(1)));
init();
