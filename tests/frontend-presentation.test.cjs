'use strict';
const {test}=require('node:test');const assert=require('node:assert/strict');
const {feasibilityModel,criticalText,scenarioName,ruleName,humanInputError}=require('../app/static/presentation.js');
test('backend feasible is the only source of the primary status',()=>{
 assert.equal(feasibilityModel({feasible:false,constraint_checks:[]}).tone,'danger');
 assert.equal(feasibilityModel({feasible:true,constraint_checks:[{ok:false,severity:'hard'}]}).tone,'success');
 assert.equal(feasibilityModel({constraint_checks:[]}).tone,'neutral');
});
test('warnings never turn an executable plan into an invalid one',()=>{
 const s=feasibilityModel({feasible:true,constraint_checks:[{ok:false,severity:'info'}],warnings:['Информация о вводе']});assert.equal(s.tone,'success');assert.equal(s.count,0);assert.equal(s.warningCount,1);
});
test('critical counter only includes failed hard checks',()=>{
 const s=feasibilityModel({feasible:false,constraint_checks:[...Array.from({length:4},()=>({ok:false,severity:'hard'})),{ok:true,severity:'hard'},{ok:false,severity:'info'}]});assert.equal(s.count,4);assert.equal(criticalText(s.count),'4 критических нарушения');
});
test('field errors retain important backend detail without presenting API paths',()=>{
 const p={decisions:{supply_orders:[{source_id:'B',year:2036}]}};const r=humanInputError({path:'decisions.supply_orders[0].ordered_t',message:'отрицательный объём: -1'},p);assert.equal(r.context,'Источник B · 2036');assert.match(r.message,/не меньше нуля/);assert.equal(r.original,'отрицательный объём: -1');
});
test('scenario and violation labels are localized without changing IDs',()=>{assert.equal(scenarioName('BASE'),'Базовый сценарий');assert.equal(scenarioName('MANDATORY_STRESS'),'Обязательный стресс-сценарий');assert.equal(ruleName('CAPACITY_EXCEEDED'),'Превышена мощность канала');});
const {warningEntries,metricNumber}=require('../app/static/presentation.js');
global.fmt=(value,digits)=>value.toLocaleString('ru-RU',{minimumFractionDigits:digits,maximumFractionDigits:digits});
test('warning presentation preserves count and only explains known backend messages',()=>{
 const result={warnings:['2035: бронь 10 т у Lunar-ISRU не действует, канал недоступен','2038: Lunar-ISRU доступен 10 мес из 12, заказ 40 т распределён по ним','Новый текст ядра'],constraint_checks:[{ok:false,severity:'soft',year:2040,source_id:'D',reason:'Пояснение ядра'},{ok:true,severity:'soft',reason:'Не показывать'}]};
 const items=warningEntries(result);assert.equal(items.length,feasibilityModel({...result,feasible:true}).warningCount);assert.match(items[0].message,/Бронь не действует/);assert.equal(items[0].context,'Источник: Lunar-ISRU · 2035 год');assert.equal(items[2].message,'Новый текст ядра');assert.equal(items[3].context,'Источник: D · 2040 год');
});
test('comparison deltas carry signs, meaningful units and neutral zeros',()=>{
 assert.equal(metricNumber(370.4,'total_cost_mln',true),'+370,4 млн');assert.equal(metricNumber(-.082,'min_service_level_total',true),'−8,2 п.п.');assert.equal(metricNumber(83.6,'shortage_total_t',true),'+83,6 т');assert.equal(metricNumber(0,'capex_total_mln',true),'0');assert.equal(metricNumber(-.00001,'losses_t',true),'0');assert.equal(metricNumber(null,'total_cost_mln',true),'—');assert.equal(metricNumber(Infinity,'total_cost_mln',true),'—');assert.equal(metricNumber(2,'hard_count',true),'+2');
});
