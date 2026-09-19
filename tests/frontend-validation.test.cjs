const {test}=require('node:test');
const assert=require('node:assert/strict');
const {validatePlan}=require('../app/static/validation.js');
const plan=require('../results/plans/base-v1.json');
const inputs={years:[2035,2036,2037,2038,2039,2040],scenarios:[{scenario_id:'BASE'},{scenario_id:'MANDATORY_STRESS'}],sources:['A','B','C','D','E'].map(id=>({id})),investments:['EARTH_NEW','LUNAR_ISRU','ZBO'].map(id=>({id})),storages:[{id:'BASE'},{id:'ZBO'}]};
const check=mutate=>{const draft=structuredClone(plan);mutate(draft);return validatePlan(draft,inputs);};
test('existing base plan passes structural validation',()=>assert.deepEqual(validatePlan(plan,inputs).errors,[]));
test('empty and malformed envelopes are blocked without throwing',()=>{for(const p of [null,[],1,'text',{}, {decisions:[]}])assert.ok(validatePlan(p,inputs).errors.length);});
test('unknown scenario, source, storage and duplicate orders are blocked',()=>{
 for(const edit of [p=>p.scenario_id='UNKNOWN',p=>p.decisions.supply_orders[0].source_id='UNKNOWN',p=>p.decisions.inventory_policy.storage_id='UNKNOWN',p=>p.decisions.supply_orders.push({...p.decisions.supply_orders[0]})])assert.ok(check(edit).errors.length);
});
test('numeric and year validation rejects negative, nonfinite and wrong types',()=>{
 for(const value of [-1,Infinity,NaN,'10',true,null])assert.ok(check(p=>p.decisions.supply_orders[0].ordered_t=value).errors.length);
 for(const value of [2034,2041,2035.5,'2035'])assert.ok(check(p=>p.decisions.supply_orders[0].year=value).errors.length);
});
test('investment dates are validated, operational feasibility is left to backend',()=>{
 assert.ok(check(p=>p.decisions.investments=[{investment_id:'EARTH_NEW',option_year:2037,exercise_year:2036}]).errors.length);
 assert.ok(check(p=>p.decisions.investments=[{investment_id:'LUNAR_ISRU',financing_years:[]}]).errors.length);
 assert.equal(check(p=>p.decisions.supply_orders[0].ordered_t=1000000).errors.length,0);
});
test('missing optional stock remains valid; no positive orders is a warning',()=>{
 const r=check(p=>{p.decisions.inventory_policy={};p.decisions.supply_orders=[];});assert.equal(r.errors.length,0);assert.ok(r.warnings.some(w=>w.path==='decisions.supply_orders'));
});
