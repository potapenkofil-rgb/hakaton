'use strict';
// Optional browser regression: NODE_PATH must expose Playwright; no app build needed.
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const baseURL=process.env.UI_BASE_URL||'http://127.0.0.1:8765';
const testPlanId=`ui-workflow-regression-${Date.now()}`;
(async()=>{
 const browser=await chromium.launch({headless:true,channel:process.env.UI_BROWSER_CHANNEL||'msedge'});
 const page=await browser.newPage({viewport:{width:1440,height:900},acceptDownloads:true});
 const errors=[];page.on('pageerror',e=>{errors.push(e.message);console.error('PAGE ERROR',e.message);});
 let calculations=0;page.on('request',r=>{if(r.url().endsWith('/api/calculate'))calculations++;});
 const waitInput=()=>page.waitForFunction(()=>!document.querySelector('#choose-json').disabled);
 const upload=async value=>{await page.locator('#plan-file').setInputFiles({name:'scenario-test.json',mimeType:'application/json',buffer:Buffer.from(typeof value==='string'?value:JSON.stringify(value))});await waitInput();};
 const review=async()=>{await page.locator('#btn-validate').click();await page.locator('#validation-view:not(.hidden)').waitFor();};
 const calculate=async()=>{const response=page.waitForResponse(r=>r.url().endsWith('/api/calculate'));await page.locator('#btn-calc').click();const res=await response;await page.locator('#results-view:not(.hidden)').waitFor();return res.json();};
 const navigate=async hash=>{await page.locator(`.sidebar nav a[href="#${hash}"]`).click();};
 try{
 await page.goto(baseURL);await waitInput();assert.equal(calculations,0);assert.equal(await page.locator('#results-view').isVisible(),false);assert.equal(await page.locator('#kpis').innerText(),'');
 for(const [width,height] of [[1920,1080],[1440,900],[1366,768],[390,844]]){await page.setViewportSize({width,height});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,`overflow ${width}`);if(process.env.UI_SCREENSHOTS){fs.mkdirSync(process.env.UI_SCREENSHOTS,{recursive:true});await page.screenshot({path:path.join(process.env.UI_SCREENSHOTS,`creation-${width}.png`)});}}
 await page.setViewportSize({width:1440,height:900});
 await review();assert.equal(await page.locator('#btn-calc').isDisabled(),true);await page.locator('#back-input').click();
 await upload('{invalid');assert.match(await page.locator('#error').innerText(),/JSON/);assert.equal(calculations,0);
 const plan=await (await page.request.get(baseURL+'/api/plans/base-v1')).json();plan.plan_id=testPlanId;plan.label='Проверка интерфейса';
 const invalid=structuredClone(plan);invalid.decisions.supply_orders[0].ordered_t=-1;await upload(invalid);await review();assert.equal(await page.locator('#btn-calc').isDisabled(),true);assert.match(await page.locator('#validation-results').innerText(),/не меньше нуля/);assert.equal(calculations,0);
 await page.locator('#back-input').click();await upload(plan);assert.equal(calculations,0);await review();assert.equal(await page.locator('#btn-calc').isEnabled(),true);
 const result=await calculate();assert.equal(result.scenario_id,'BASE');assert.equal(result.feasible,true);assert.equal(await page.locator('.kpi').count(),5);
 for(const [width,height] of [[1920,1080],[1440,900],[1366,768],[390,844]]){await page.setViewportSize({width,height});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,`results overflow ${width}`);if(process.env.UI_SCREENSHOTS)await page.screenshot({path:path.join(process.env.UI_SCREENSHOTS,`results-${width}.png`)});}
 await page.setViewportSize({width:1440,height:900});
 const before=await page.locator('#balance-chart polyline').count();await page.locator('#balance-legend button').first().click();assert.equal(await page.locator('#balance-chart polyline').count(),before-1);await page.locator('#balance-legend button').first().click();
 await page.locator('#balance-chart circle').first().hover();await page.locator('#chart-tooltip:not(.hidden)').waitFor();assert.match(await page.locator('#chart-tooltip').innerText(),/т/);
 await page.locator('#source-legend button').first().click();assert.equal(await page.locator('#source-legend button').first().getAttribute('aria-pressed'),'false');
 await page.locator('#chart-from').selectOption('2038');assert.equal(await page.locator('#balance-chart circle').count(),6);
 const stressResponse=page.waitForResponse(r=>r.url().endsWith('/api/calculate'));await page.locator('#result-scenario-select').selectOption('MANDATORY_STRESS');const stress=await (await stressResponse).json();await page.locator('#results-view:not(.hidden)').waitFor();assert.equal(stress.feasible,false);assert.equal(stress.scenario_id,'MANDATORY_STRESS');
 await page.locator('#edit-results').click();const order=page.locator('#editor input[data-kind="order"][data-src="A"][data-year="2035"]');await order.fill('114');const countBefore=calculations;assert.equal(await page.locator('#results-view').isVisible(),false);assert.equal(await page.locator('.sidebar nav a[href="#overview"]').getAttribute('aria-disabled'),'true');await review();const changed=await calculate();assert.notEqual(changed.yearly_balance[0].delivered_actual_t,stress.yearly_balance[0].delivered_actual_t);assert.equal(calculations,countBefore+1);
 await page.locator('#to-reports').click();await page.locator('#btn-compare').click();await page.locator('#sec-compare:not(.hidden)').waitFor();assert.ok(await page.locator('#compare-yearly tbody tr').count()>0);
 for(const id of ['btn-csv','btn-xlsx','btn-download']){const pending=page.waitForEvent('download');await page.locator('#'+id).click();const d=await pending;assert.equal(await d.failure(),null);assert.ok((await fs.promises.stat(await d.path())).size>0);console.log('download',d.suggestedFilename());}
 await navigate('scenarios');await page.locator('#btn-save').click();await page.waitForFunction(()=>document.querySelector('#status').textContent.includes('Сохранено на сервере'));
 await page.locator('#btn-reset').click();assert.equal(await page.locator('#kpis').isVisible(),false);await page.locator('#choose-saved').click();await page.locator('#plan-list').selectOption(testPlanId);await page.locator('#btn-open').click();await waitInput();assert.equal(await page.locator('#plan-id').inputValue(),'Проверка интерфейса');assert.equal(await order.inputValue(),'114');
 // Search navigates sections only; saved plans have an explicit Open control.
 await page.locator('#search').fill('Сценарий');await page.locator('#search-results button').first().click();assert.equal(await page.locator('#search').inputValue(),'');assert.equal(await page.locator('#search-clear').isVisible(),false);assert.equal(await page.locator('#plan-id').inputValue(),'Проверка интерфейса');
 // Raw edits cannot bypass review of the applied state.
 await page.locator('#controls').evaluate(e=>e.open=true);await page.locator('#raw-panel').evaluate(e=>e.open=true);await page.locator('#raw-plan').fill('{}');await review();assert.equal(await page.locator('#btn-calc').isDisabled(),true);assert.match(await page.locator('#validation-results').innerText(),/не применён/);
 await page.locator('#back-input').click();await page.locator('#btn-reset').click();await page.locator('#choose-manual').click();await page.locator('#plan-id').fill('Ручной сценарий');await order.fill('50');await page.locator('#editor input[data-kind="res"][data-src="A"][data-year="2035"]').fill('60');assert.match(await page.locator('#scenario-summary').innerText(),/1 источн/);await review();assert.equal(await page.locator('#btn-calc').isEnabled(),true);await calculate();
 // Network failure is visible and recoverable, without exposing stale KPIs.
 await page.locator('#edit-results').click();await order.fill('51');await review();await page.route('**/api/calculate',r=>r.fulfill({status:500,contentType:'text/html',body:'server unavailable'}));await page.locator('#btn-calc').click();await page.locator('#error:not(.hidden)').waitFor();assert.match(await page.locator('#error').innerText(),/Не удалось выполнить действие/);assert.equal(await page.locator('#results-view').isVisible(),false);await page.unroute('**/api/calculate');await calculate();
 await page.locator('#edit-results').click();await order.fill('52');await review();
 await page.route('**/api/calculate',r=>r.fulfill({status:400,contentType:'application/json',body:JSON.stringify({error:'INVALID_PLAN',details:[{path:'decisions.supply_orders[0].ordered_t',message:'Тест ошибки серверной валидации'}]})}));
 await page.locator('#btn-calc').click();await page.locator('#error:not(.hidden)').waitFor();assert.equal(await page.locator('#error').getAttribute('data-error'),'INVALID_PLAN');assert.equal(await page.locator('#btn-calc').isDisabled(),true);await page.unroute('**/api/calculate');
 await page.locator('#back-input').click();await order.fill('53');await review();
 let release;const gate=new Promise(resolve=>release=resolve);await page.route('**/api/calculate',async r=>{await gate;await r.continue();});
 await page.locator('#btn-calc').click();await page.locator('#calculating-view:not(.hidden)').waitFor();assert.equal(await page.locator('#results-view').isVisible(),false);release();await page.locator('#results-view:not(.hidden)').waitFor();await page.unroute('**/api/calculate');
 // Failed reference-data loading can be retried without a page reload.
 await page.route('**/api/inputs',r=>r.fulfill({status:503,contentType:'text/html',body:'unavailable'}));await page.reload();await page.locator('#retry-inputs:not(.hidden)').waitFor();await page.unroute('**/api/inputs');await page.locator('#retry-inputs').click();await waitInput();assert.equal(await page.locator('#results-view').isVisible(),false);
 assert.deepEqual(errors,[]);console.log('PASS: empty start, validation, JSON/manual/saved inputs, real calculations, charts, search, save/open, compare/export, errors, responsive; no JS errors.');
 }finally{
   await browser.close();
   // Only remove this run's uniquely named files in the local repository.
   for(const file of [path.join('plans',testPlanId+'.json'),...['csv','xlsx'].map(ext=>path.join('exports',testPlanId+'_MANDATORY_STRESS.'+ext))])fs.rmSync(path.join(__dirname,'..','results',file),{force:true});
 }

})().catch(e=>{console.error(e);process.exit(1);});


