'use strict';
// Acceptance checks use real API results, including BASE invalid / STRESS valid.
const {chromium}=require('playwright');const assert=require('node:assert/strict');const fs=require('node:fs');const path=require('node:path');
const inverse=require('./frontend-fixtures/inverse-plan.json');const baseURL=process.env.UI_BASE_URL||'http://127.0.0.1:8765';
(async()=>{
 const browser=await chromium.launch({headless:true,channel:process.env.UI_BROWSER_CHANNEL||'msedge'});const p=await browser.newPage({viewport:{width:1366,height:768}});const errors=[];p.on('pageerror',e=>errors.push(e.message));
 const shot=async name=>{if(process.env.UI_SCREENSHOTS){fs.mkdirSync(process.env.UI_SCREENSHOTS,{recursive:true});await p.screenshot({path:path.join(process.env.UI_SCREENSHOTS,name+'.png')});}};
 const noOverflow=async()=>assert.equal(await p.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
 const ready=()=>p.waitForFunction(()=>!document.querySelector('#choose-json').disabled);
 const nav=async id=>{await p.locator(`.sidebar nav a[href="#${id}"]`).click();await p.waitForFunction(()=>navigationTarget===null);};
 try{
 await p.goto(baseURL);await ready();assert.doesNotMatch(await p.locator('body').innerText(),/Лимит запусков|Не поддерживается API/);assert.match(await p.locator('#scenario-summary').innerText(),/Расчёт не выполнен/);
 for(const [width,height] of [[1920,1080],[1600,900],[1366,768]]){await p.setViewportSize({width,height});await noOverflow();await shot('empty-'+width);}
 await p.locator('#plan-file').setInputFiles({name:'inverse-plan.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(inverse))});await ready();assert.equal(await p.locator('#error').isVisible(),false);await p.locator('#btn-validate').click();assert.equal(await p.locator('#btn-calc').isEnabled(),true);
 let release;const gate=new Promise(resolve=>release=resolve);await p.route('**/api/calculate',async r=>{await gate;await r.continue();});const response=p.waitForResponse(r=>r.url().endsWith('/api/calculate'));await p.locator('#btn-calc').click();await p.locator('#calculating-view:not(.hidden)').waitFor();assert.equal(await p.locator('#results-view').isVisible(),false);assert.ok(await p.locator('#calculating-view .skeleton-grid').isVisible());release();const actual=await (await response).json();await p.unroute('**/api/calculate');await p.locator('#results-view:not(.hidden)').waitFor();
 assert.equal(actual.feasible,false);assert.equal(actual.constraint_checks.filter(c=>!c.ok&&c.severity==='hard').length,4);assert.equal(await p.locator('#result-plan-status .danger').count(),1);assert.match(await p.locator('#result-plan-status').innerText(),/4 критических нарушения/);
 await shot('base-invalid');await p.locator('#result-plan-status .status-link').click();await p.waitForFunction(()=>navigationTarget===null);assert.equal(await p.locator('#critical-issues .violation-card').count(),4);assert.equal(await p.locator('.sidebar nav a.active').getAttribute('href'),'#sec-violations');
 // Scroll in both directions across boundaries; only one sidebar item may be active.
 for(const id of ['economics','logistics','infrastructure','balance-detail','overview','infrastructure','economics']){
   await p.locator('#'+id).evaluate(el=>window.scrollTo({top:window.scrollY+el.getBoundingClientRect().top-83,behavior:'instant'}));
   await p.waitForFunction(id=>document.querySelector('.sidebar nav a.active')?.hash==='#'+id,id);
   assert.equal(await p.locator('.sidebar nav a.active').count(),1);
 }
 await nav('logistics');assert.equal(await p.locator('.sidebar nav a.active').getAttribute('href'),'#logistics');
 await p.locator('#logistics details summary').click();await noOverflow();await nav('overview');
 // Export view gives feasibility and summary first; comparison preserves its space.
 await p.locator('#to-reports').click();await p.waitForFunction(()=>navigationTarget===null);assert.match(await p.locator('#report-plan-status').innerText(),/План неисполним/);
 const before=await p.locator('#report-issues').evaluate(el=>el.getBoundingClientRect().top+window.scrollY);
 let releaseCompare;const compareGate=new Promise(resolve=>releaseCompare=resolve);await p.route('**/api/compare',async r=>{await compareGate;await r.continue();});const compareResponse=p.waitForResponse(r=>r.url().endsWith('/api/compare'));await p.locator('#btn-compare').click();await p.locator('#compare-loading:not(.hidden)').waitFor();assert.equal(await p.locator('.comparison-slot').getAttribute('aria-busy'),'true');releaseCompare();const cmp=await (await compareResponse).json();await p.locator('#sec-compare:not(.hidden)').waitFor();await p.unroute('**/api/compare');
 assert.equal(cmp.feasible.BASE,false);assert.equal(cmp.feasible.MANDATORY_STRESS,true);assert.equal(await p.locator('#comparison-statuses .plan-status').nth(0).getAttribute('data-feasible'),'false');assert.equal(await p.locator('#comparison-statuses .danger').count(),1);assert.equal(await p.locator('#comparison-statuses .success').count(),1);assert.equal(await p.locator('#compare-summary tbody tr').count(),7);assert.equal(await p.locator('#status').getAttribute('class'),'status ');
 const after=await p.locator('#report-issues').evaluate(el=>el.getBoundingClientRect().top+window.scrollY);assert.ok(Math.abs(after-before)<80,`comparison layout shift: ${after-before}`);
 await nav('comparison');await shot('independent-statuses');
 for(const [width,height] of [[1920,1080],[1600,900],[1366,768]]){await p.setViewportSize({width,height});await noOverflow();await shot('comparison-'+width);}
 // Warning-only result remains executable, warnings have separate yellow styling.
 await nav('scenarios');await p.locator('#choose-saved').click();await p.locator('#plan-list').selectOption('base-v1');await p.locator('#btn-open').click();await ready();await p.locator('#btn-validate').click();await p.locator('#btn-calc').click();await p.locator('#results-view:not(.hidden)').waitFor();assert.equal(await p.locator('#result-plan-status .success').count(),1);assert.ok(await p.locator('#result-plan-status .warning-tag').count()>0);await nav('sec-violations');assert.ok(await p.locator('.notice.warning li').count()>0);assert.match(await p.locator('#critical-issues').innerText(),/Критических нарушений нет/);
 // Friendly invalid JSON/field errors leave the app operable.
 await nav('scenarios');await p.locator('#plan-file').setInputFiles({name:'broken.json',mimeType:'application/json',buffer:Buffer.from('{broken')});await p.locator('#error:not(.hidden)').waitFor();assert.match(await p.locator('#error').innerText(),/не является корректным JSON/);
 const invalid=structuredClone(inverse);invalid.decisions.supply_orders[0].ordered_t=-1;await p.locator('#plan-file').setInputFiles({name:'negative.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(invalid))});await ready();await p.locator('#btn-validate').click();assert.equal(await p.locator('#btn-calc').isDisabled(),true);assert.doesNotMatch(await p.locator('#validation-results').innerText(),/decisions\.supply_orders/);assert.match(await p.locator('#validation-results').innerText(),/Источник A · 2035/);
 assert.deepEqual(errors,[]);console.log('PASS acceptance 1–10: real inverse feasibility, four hard violations, independent colors, warnings, JSON, scrollspy, loading, comparison stability, 1920/1600/1366.');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
