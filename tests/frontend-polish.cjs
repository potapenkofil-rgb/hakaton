'use strict';
// Real server required. Seven fixtures are byte-identical copies supplied by the user.
const {chromium}=require('playwright');
const assert=require('node:assert/strict');const fs=require('node:fs');const path=require('node:path');
const fixtures={"happy-base": "01_happy_base_feasible", "happy-stress": "02_happy_stress_feasible", "warning": "03_warning_unavailable_reservation", "empty": "04_valid_empty_infeasible", "capacity-reservation": "05_hard_capacity_and_reservation", "stress-no-zbo": "06_stress_without_zbo", "invalid-multiple": "07_invalid_multierror"};
const baseURL=process.env.UI_BASE_URL||'http://127.0.0.1:8765';
(async()=>{
 const browser=await chromium.launch({headless:true,channel:process.env.UI_BROWSER_CHANNEL||'msedge'});
 const p=await browser.newPage({viewport:{width:1366,height:768}}),errors=[];p.on('pageerror',e=>errors.push(e.message));
 const ready=()=>p.waitForFunction(()=>!document.querySelector('#choose-json').disabled);
 const shot=async name=>{if(process.env.UI_SCREENSHOTS){fs.mkdirSync(process.env.UI_SCREENSHOTS,{recursive:true});await p.screenshot({path:path.join(process.env.UI_SCREENSHOTS,name+'.png')});}};
 const nav=async id=>{await p.locator(`.sidebar nav a[href="#${id}"]`).click();await p.waitForFunction(()=>navigationTarget===null);};
 const noOverflow=async()=>assert.equal(await p.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
 const upload=async name=>{await nav('scenarios');await p.locator('#plan-file').setInputFiles(path.join(__dirname,'frontend-fixtures',fixtures[name]+'.json'));await p.waitForFunction(id=>state.plan?.plan_id===id&&state.phase==='DRAFT',require('./frontend-fixtures/'+fixtures[name]+'.json').plan_id);await ready();};
 const fingerprint=()=>p.evaluate(()=>JSON.stringify([state.plan,state.result,state.comparison,state.revision,state.step]));
 const sidebar=()=>p.locator('.sidebar nav a').evaluateAll(els=>els.map(e=>({text:e.textContent,visible:e.getBoundingClientRect().height>0&&getComputedStyle(e).visibility!=='hidden'})));
 const fixtureNames=['happy-base','happy-stress','warning','empty','capacity-reservation','stress-no-zbo','invalid-multiple'];
 try{
 await p.goto(baseURL);await ready();const menu=await sidebar();assert.equal(menu.length,9);assert.ok(menu.every(e=>e.visible));assert.equal(await p.locator('#search-clear').isVisible(),false);assert.equal(await p.locator('#readiness .check.yes').count(),0);
 // Search before calculation: unavailable destinations are visible but disabled.
 await p.locator('#search').fill('риски');assert.equal(await p.locator('#search-results button').isDisabled(),true);await p.locator('#search').press('Escape');assert.equal(await p.locator('#search-results').isVisible(),false);
 await p.locator('#search').fill('Сценарий');await p.locator('#search-results button').click();assert.equal(await p.locator('#search-clear').isVisible(),false);
 for(const name of fixtureNames){
   await upload(name);const preparation=await p.locator('.readiness-count').innerText();
   await p.locator('#btn-validate').click();const validation=await p.evaluate(()=>state.validation);
   assert.match(preparation,new RegExp(`Ошибок: ${validation.errors.length} · Предупреждений: ${validation.warnings.length}`));
   if(name==='invalid-multiple'){
     assert.ok(validation.errors.length>=6);assert.equal(await p.locator('#btn-calc').isDisabled(),true);
     await p.locator('#back-input').click();assert.ok(await p.locator('#readiness [data-tone=bad]').count()>=4);assert.doesNotMatch(await p.locator('#readiness').innerText(),/decisions\./);await shot('invalid-readiness');
     await p.locator('#btn-validate').click();const button=p.locator('#btn-calc');await button.scrollIntoViewIfNeeded();await p.mouse.move(0,0);await p.waitForTimeout(100);
     const appearance=()=>button.evaluate(e=>({rect:e.getBoundingClientRect().toJSON(),background:getComputedStyle(e).backgroundColor,cursor:getComputedStyle(e).cursor}));const before=await appearance();await button.hover();const after=await appearance();assert.deepEqual(after,before);assert.notEqual(after.background,'rgba(0, 0, 0, 0)');assert.equal(after.cursor,'not-allowed');await shot('disabled-hover');
     const invalid=require('./frontend-fixtures/07_invalid_multierror.json');const r=await p.request.post(baseURL+'/api/calculate',{data:{plan:invalid}});assert.equal(r.status(),400);assert.equal((await r.json()).error,'INVALID_PLAN');console.log(name,`local errors=${validation.errors.length}; API INVALID_PLAN; hover stable`);continue;
   }
   assert.equal(validation.errors.length,0);const response=p.waitForResponse(r=>r.url().endsWith('/api/calculate'));await p.locator('#btn-calc').click();const result=await (await response).json();await p.locator('#results-view:not(.hidden)').waitFor();await p.waitForFunction(()=>navigationTarget===null);
   const hard=result.constraint_checks.filter(c=>c.ok===false&&c.severity==='hard');const warningCount=result.warnings.length+result.constraint_checks.filter(c=>c.ok===false&&['soft','warning'].includes(c.severity)).length;
   assert.equal(result.feasible,['happy-base','happy-stress','warning'].includes(name));assert.equal(await p.locator('#critical-issues .violation-card').count(),hard.length);assert.equal(await p.locator('#warning-issues li').count(),warningCount);
   assert.equal(await p.locator('#result-plan-status .plan-status').getAttribute('data-feasible'),String(result.feasible));assert.doesNotMatch(await p.locator('#dashboard').innerText(),/NaN|undefined|Infinity/);assert.doesNotMatch(await p.locator('#balance-chart').innerHTML(),/NaN|undefined|Infinity/);
   if(warningCount){const saved=await fingerprint();await p.locator('#result-plan-status .warning-tag').click();assert.equal(await p.locator('#result-plan-status .warning-list li').count(),warningCount);assert.equal(await fingerprint(),saved);await shot('warnings-'+name);}
   if(name==='warning'){assert.match(await p.locator('#warning-issues').innerText(),/Lunar-ISRU · 2035 год/);assert.match(await p.locator('#warning-issues').innerText(),/Бронь не действует/);assert.equal(await p.locator('#violations').evaluate(e=>e.closest('details').hidden),true);}
   if(name==='empty'){assert.equal(result.feasible,false);assert.equal(hard.length,18);}
   if(name==='capacity-reservation'){assert.ok(hard.some(c=>c.rule_id==='CAPACITY_EXCEEDED'));assert.ok(hard.some(c=>c.rule_id==='ORDER_EXCEEDS_RESERVATION'));}
   if(name==='stress-no-zbo')assert.ok(hard.some(c=>c.rule_id==='STRESS_LOSS_LIMIT'));
   assert.deepEqual(await sidebar(),menu);await noOverflow();console.log(name,`feasible=${result.feasible}; hard=${hard.length}; warnings=${warningCount}`);
 }
 // Search after calculation must preserve plan/result/revision and step 4.
 await upload('happy-base');await p.locator('#btn-validate').click();await p.locator('#btn-calc').click();await p.locator('#results-view:not(.hidden)').waitFor();
 const saved=await fingerprint();await p.locator('#search').fill('риски');await p.locator('#search-results button').click();await p.waitForFunction(()=>navigationTarget===null);assert.equal(await fingerprint(),saved);assert.equal(await p.locator('#search-clear').isVisible(),false);assert.equal(await p.locator('.sidebar .active').getAttribute('href'),'#sec-violations');
 for(const key of ['Backspace','Delete']){await p.locator('#search').fill('риски');await p.locator('#search').press('ControlOrMeta+A');await p.locator('#search').press(key);assert.equal(await p.locator('#search-clear').isVisible(),false);}
 await p.locator('#search').fill('р');await p.locator('#search').press('Backspace');assert.equal(await p.locator('#search-clear').isVisible(),false);
 await p.locator('#search').fill('риски');await p.locator('#search').press('Escape');assert.equal(await p.locator('#search-results').isVisible(),false);assert.equal(await p.locator('#search-clear').isVisible(),true);
 await p.locator('#search').click();assert.equal(await p.locator('#search-results').isVisible(),true);await p.locator('.top-note').click();assert.equal(await p.locator('#search-results').isVisible(),false);await p.locator('#search-clear').click();assert.equal(await p.locator('#search-clear').isVisible(),false);assert.equal(await fingerprint(),saved);
 // Traverse every section with small scroll steps, not direct jumps to section IDs.
 const expected=['overview','balance-detail','infrastructure','logistics','economics','sec-violations'].map(s=>'#'+s);
 for(const [width,height] of [[1920,1080],[1600,900],[1366,768]]){
   await p.setViewportSize({width,height});await nav('overview');await p.evaluate(()=>window.scrollTo({top:0,behavior:'instant'}));await p.waitForTimeout(50);
   const max=await p.evaluate(()=>document.documentElement.scrollHeight-innerHeight),sequence=[];
   for(const y of [...Array.from({length:Math.ceil(max/20)},(_,i)=>i*20),max]){
     await p.evaluate(y=>window.scrollTo({top:y,behavior:'instant'}),y);await p.waitForTimeout(22);const id=await p.locator('.sidebar .active').getAttribute('href');if(sequence.at(-1)!==id)sequence.push(id);assert.deepEqual(await sidebar(),menu);
   }
   assert.deepEqual(sequence,expected,`down ${width}`);const reverse=[];
   for(const y of [...Array.from({length:Math.ceil(max/20)},(_,i)=>Math.max(0,max-i*20)),0]){
     await p.evaluate(y=>window.scrollTo({top:y,behavior:'instant'}),y);await p.waitForTimeout(22);const id=await p.locator('.sidebar .active').getAttribute('href');if(reverse.at(-1)!==id)reverse.push(id);
   }
   assert.deepEqual(reverse,[...expected].reverse(),`up ${width}`);await noOverflow();await shot('results-'+width);console.log(`scroll ${width}: ${sequence.join(' → ')}; reverse OK`);
 }
 await nav('comparison');await p.locator('#btn-compare').click();await p.locator('#sec-compare:not(.hidden)').waitFor();const comparison=await p.evaluate(()=>state.comparison);
 assert.equal(await p.locator('#reports-view a[href="#sec-violations"]').count(),0);assert.match(await p.locator('#compare-summary thead').innerText(),/Разница STRESS − BASE/);
 assert.doesNotMatch(await p.locator('#compare-totals').innerText(),/total_|service_|_mln|Дополнительный показатель/);
 assert.doesNotMatch(await p.locator('#compare-yearly').innerText(),/total_|service_|_mln|Дополнительный показатель/);
 const delta=await p.locator('#compare-summary tbody tr').evaluateAll(rows=>rows.map(r=>r.lastElementChild.textContent));assert.match(delta[0],/^[+−].*млн$/);assert.equal(delta[2],'0');assert.match(delta[5],/^[+−].*п.п.$/);
 const comparisonState=await fingerprint();
 for(const block of await p.locator('#reports-view .warning-details').all()){await block.locator('summary').click();assert.equal(await fingerprint(),comparisonState);await block.locator('summary').click();}
 for(const [width,height] of [[1920,1080],[1600,900],[1366,768]]){
   await p.setViewportSize({width,height});await nav('comparison');await shot('comparison-'+width);await p.locator('#comparison-details summary').click();await p.locator('#comparison-details').scrollIntoViewIfNeeded();await p.locator('#compare-yearly').evaluate(e=>{const box=e.parentElement;box.scrollTop+=e.getBoundingClientRect().top-box.getBoundingClientRect().top;});await noOverflow();
   const sizes=await p.locator('#compare-yearly').evaluate(e=>({table:e.getBoundingClientRect().width,container:e.parentElement.clientWidth,body:document.documentElement.scrollWidth,viewport:innerWidth}));assert.ok(sizes.table<=sizes.container+1);assert.ok(sizes.body<=sizes.viewport);await shot('full-table-'+width);await p.locator('#comparison-details summary').click();
 }
 assert.equal(await p.locator('#compare-yearly tbody tr').count(),comparison.yearly.length);assert.equal(await p.locator('#compare-totals tbody tr').count(),comparison.totals.length);
 assert.deepEqual(errors,[]);console.log('PASS final polish: 7 JSON cases; stable sidebar down/up; search state; readiness; warnings; hover; comparison units/layout; no JS errors.');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
