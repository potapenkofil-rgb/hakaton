/* Input validation mirrors the structure and field rules in fuelhub/plan.py.
   No capacity, delivery, price, service or financial calculations belong here. */
(function(root) {
  function validatePlan(plan, inputs) {
    const errors = [], warnings = [], passed = [];
    const object = v => v !== null && typeof v === 'object' && !Array.isArray(v);
    const fail = (path, message) => errors.push({path, message});
    if (!inputs) return {errors:[{path:'inputs',message:'Справочники ещё не загружены.'}], warnings, passed};
    if (!object(plan)) return {errors:[{path:'plan',message:'Создайте сценарий, загрузите JSON или откройте сохранённый план.'}], warnings, passed};
    if (typeof plan.plan_id !== 'string' || !plan.plan_id.trim()) fail('plan_id','Нужен непустой идентификатор плана.');
    else if (!plan.plan_id.replace(/[^A-Za-z0-9._-]+/g,'-').replace(/^[-.]+|[-.]+$/g,'')) fail('plan_id','Для сохранения идентификатор должен содержать латинскую букву или цифру. Название может быть на русском.');
    if (!inputs.scenarios.some(s=>s.scenario_id === plan.scenario_id)) fail('scenario_id','Выберите существующий расчётный сценарий.');
    const d=plan.decisions;
    if (!object(d)) { fail('decisions','Нужен объект решений: заказы, брони, инвестиции и политика запаса.'); return {errors,warnings,passed}; }
    const number=(obj,key,path,required=true)=>{
      if (!(key in obj) && !required) return;
      if (typeof obj[key] !== 'number' || !Number.isFinite(obj[key]) || obj[key]<0) fail(`${path}.${key}`,'Введите конечное неотрицательное число.');
    };
    const year=(obj,key,path)=>{if(!Number.isInteger(obj[key]) || !inputs.years.includes(obj[key])) fail(`${path}.${key}`,`Год должен входить в период ${inputs.years[0]}–${inputs.years.at(-1)}.`);};
    for(const [key,field] of [['supply_orders','ordered_t'],['capacity_reservations','reserved_capacity_t']]) {
      if(!Array.isArray(d[key])) {fail(`decisions.${key}`,'Нужен массив строк.'); continue;}
      const seen=new Set();
      d[key].forEach((row,i)=>{
        const path=`decisions.${key}[${i}]`;
        if(!object(row)) {fail(path,'Нужен объект с каналом, годом и объёмом.');return;}
        if(!inputs.sources.some(s=>s.id===row.source_id)) fail(`${path}.source_id`,'Неизвестный источник поставок.');
        year(row,'year',path);number(row,field,path);
        const id=JSON.stringify([row.source_id,row.year]);
        if(seen.has(id)) fail(path,'Канал и год заданы дважды. Объедините строки в одну.');
        seen.add(id);
      });
    }
    if(!Array.isArray(d.investments)) fail('decisions.investments','Нужен массив инвестиций.');
    else {
      const seen=new Set();
      d.investments.forEach((inv,i)=>{
        const path=`decisions.investments[${i}]`;
        if(!object(inv)) {fail(path,'Нужен объект инвестиции.');return;}
        if(!inputs.investments.some(v=>v.id===inv.investment_id)) fail(`${path}.investment_id`,'Неизвестная инвестиция.');
        if(seen.has(inv.investment_id)) fail(path,'Инвестиция задана дважды.');
        seen.add(inv.investment_id);
        if(inv.investment_id==='EARTH_NEW') {
          year(inv,'option_year',path);year(inv,'exercise_year',path);
          if(inv.exercise_year<inv.option_year) fail(`${path}.exercise_year`,'Исполнение не может быть раньше оплаты опциона.');
        } else if(inv.investment_id==='LUNAR_ISRU') {
          const years=inv.financing_years ?? (inv.year===undefined?null:[inv.year]);
          if(!Array.isArray(years)||!years.length) fail(`${path}.financing_years`,'Выберите хотя бы один год финансирования.');
          else years.forEach((v,j)=>year({year:v},'year',`${path}.financing_years[${j}]`));
        } else year(inv,'year',path);
      });
    }
    const ip=d.inventory_policy;
    if(!object(ip)) fail('decisions.inventory_policy','Нужен объект политики запаса.');
    else {
      number(ip,'initial_stock_t','decisions.inventory_policy',false);number(ip,'initial_stock_cost_mln','decisions.inventory_policy',false);
      if(ip.initial_stock_source_id!=null&&!inputs.sources.some(s=>s.id===ip.initial_stock_source_id)) fail('decisions.inventory_policy.initial_stock_source_id','Неизвестный канал начального запаса.');
      if(!inputs.storages.some(s=>s.id===(ip.storage_id??'BASE'))) fail('decisions.inventory_policy.storage_id','Неизвестное хранилище.');
    }
    if(Array.isArray(d.supply_orders)&&!d.supply_orders.some(r=>r?.ordered_t>0)) warnings.push({path:'decisions.supply_orders',message:'Положительные заказы отсутствуют. Расчёт разрешён, но поставки могут не покрыть спрос.'});
    for(const [path,label] of [['plan_id','Идентификатор плана'],['scenario_id','Расчётный сценарий'],['decisions.supply_orders','Заказы поставок'],['decisions.capacity_reservations','Бронирование мощностей'],['decisions.investments','Инвестиционные решения'],['decisions.inventory_policy','Политика запаса']]) {
      if(!errors.some(e=>e.path===path||e.path.startsWith(path+'.')||e.path.startsWith(path+'['))) passed.push({path,message:`${label}: формат и значения корректны.`});
    }
    return {errors,warnings,passed};
  }
  root.validatePlan=validatePlan;
  if(typeof module!=='undefined') module.exports={validatePlan};
})(globalThis);
