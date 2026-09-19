// Run against `python -m fuelhub serve`; requires Playwright and Chrome.
// NODE_PATH may point to the bundled Codex Node packages.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

(async () => {
  const out = path.resolve('results/exports/ui-review');
  fs.mkdirSync(out, { recursive: true });
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  page.on('console', msg => { if (msg.type() === 'error' && !msg.text().includes('400 (Bad Request)') && !msg.text().includes('500 (Internal Server Error)')) errors.push(msg.text()); });
  const log = [];
  const check = (name) => { log.push(name); console.log('PASS', name); };
  const calculate = async (action, status = 200) => {
    const response = page.waitForResponse(r => r.url().endsWith('/api/calculate') && r.request().method() === 'POST');
    await action();
    const res = await response;
    assert.equal(res.status(), status);
    const data = await res.json();
    if (status === 200) await page.waitForFunction(id => state.result?.plan_id === id && !document.querySelector('#status').classList.contains('wait'), data.plan_id);
    else await page.locator('#error:not(.hidden)').waitFor();
    return data;
  };
  const plan = id => calculate(() => page.locator('#plan-list').selectOption(id), id === 'invalid' ? 400 : 200);
  const scenario = id => calculate(() => page.locator(`#scenario button[data-id="${id}"]`).click());
  try {
    await page.goto('http://127.0.0.1:8765/');
    await page.waitForFunction(() => state.result !== null);
    assert.equal(await page.locator('#engine').count(), 0);
    assert.equal(await page.evaluate(() => state.result.feasible), true);
    assert.deepEqual(await page.locator('.brand img').evaluate(img => [img.complete, img.naturalWidth, img.naturalHeight]), [true, 2508, 627]);
    check('initial v3-earth BASE, original PNG logo, no engine footer');
    for (const width of [1024, 1280, 1366, 1440, 1920]) {
      await page.setViewportSize({ width, height: 1000 });
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
      const logo = await page.locator('.brand img').boundingBox();
      assert(Math.abs(logo.width / logo.height - 4) < .01);
      await page.screenshot({ path: path.join(out, `overview-${width}.png`) });
      check(`viewport ${width}: no page overflow`);
    }
    await page.setViewportSize({ width: 1440, height: 1000 });
    const stress = await scenario('MANDATORY_STRESS');
    assert.equal(stress.feasible, false);
    assert(stress.totals.shortage_total_t > 140);
    const year = page.locator('.demand-year[data-year="2040"] [data-metric="shortage_total_t"]');
    await year.hover();
    assert((await page.locator('#demand-tooltip').innerText()).includes('122,5 т'));
    await year.click();
    assert.equal(await year.getAttribute('aria-pressed'), 'true');
    assert.equal(await page.locator('#balance-table .selected-year td').first().innerText(), '2040');
    await year.focus();
    await page.keyboard.press('Space');
    assert.equal(await year.getAttribute('aria-pressed'), 'false');
    await page.keyboard.press('Enter');
    assert.equal(await year.getAttribute('aria-pressed'), 'true');
    await page.locator('#chart-demand').screenshot({ path: path.join(out, 'demand-tooltip.png') });
    await page.keyboard.press('Escape');
    assert.equal(await page.locator('#balance-table .selected-year').count(), 0);
    for (const metric of ['demand_total_t', 'delivered_actual_t', 'served_total_t']) {
      const bar = page.locator(`.demand-year[data-year="2039"] [data-metric="${metric}"]`);
      await bar.hover();
      assert.equal(await page.locator('#demand-tooltip dt').count(), 1);
      assert.equal(await page.locator('#demand-tooltip dt').innerText(), await bar.getAttribute('data-label'));
      assert.equal(await page.locator('#demand-tooltip dd').innerText(), stress.yearly_balance.find(r => r.year === 2039)[metric].toLocaleString('ru-RU', {minimumFractionDigits: 1, maximumFractionDigits: 1}) + ' т');
    }
    const bars = page.locator('.demand-year[data-year="2039"] rect.demand-item');
    const leftBar = await bars.nth(0).boundingBox(), rightBar = await bars.nth(1).boundingBox();
    await page.mouse.move((leftBar.x + leftBar.width + rightBar.x) / 2, Math.max(leftBar.y, rightBar.y) + 20);
    assert.equal(await page.locator('#demand-tooltip').isVisible(), false);
    check('single metric tooltips match backend; gap between bars has no tooltip');
    await page.locator('#chart-stock svg').hover();
    assert.equal(await page.locator('#chart-stock .hover').evaluate(el => el.style.display), '');
    assert((await page.locator('#schedule-table').innerText()).includes('до начала 2035'));
    assert((await page.locator('#schedule-table span[title]').first().getAttribute('title')).includes('обязательство принято заранее'));
    assert.deepEqual(await page.evaluate(() => [formatOrderBy(''), formatOrderBy('2037-09'), formatOrderBy('<unknown>')]), ['—', '<span title="2037-09">сен. 2037</span>', '<span title="&lt;unknown&gt;">&lt;unknown&gt;</span>']);
    check('stress, both hovers, demand click/focus/Space/Enter/Escape, deadline formatting');
    const cmpResponse = page.waitForResponse(r => r.url().endsWith('/api/compare'));
    await page.locator('#btn-compare').click();
    const cmp = await (await cmpResponse).json();
    await page.locator('#compare:not(.hidden)').waitFor();
    assert.equal(await page.locator('.scenario-card').count(), 2);
    for (const [i, id] of cmp.scenarios.entries()) {
      const pv = cmp.totals.find(r => r.metric === 'pv_total_mln')[id];
      assert((await page.locator('.scenario-card').nth(i).innerText()).includes(pv.toLocaleString('ru-RU', { maximumFractionDigits: 0 })));
    }
    await page.locator('#compare').screenshot({ path: path.join(out, 'compare.png') });
    check('comparison conclusions and PV match API');
    await plan('v3-earth-response');
    assert.equal((await scenario('MANDATORY_STRESS')).feasible, true);
    assert.equal((await scenario('BASE')).feasible, false);
    await plan('v3-earth');
    const team = await calculate(() => page.locator('#scenario-team').selectOption('TEAM_HIGH_DEMAND'));
    assert.equal(team.feasible, false);
    await scenario('BASE');
    check('response stress/BASE and TEAM_HIGH_DEMAND');
    const order = page.locator('#orders input[data-src="A"][data-year="2035"]');
    await order.fill('200');
    assert((await calculate(() => order.press('Enter'))).constraint_checks.some(c => !c.ok && c.rule_id === 'CAPACITY_EXCEEDED'));
    await order.fill('95');
    assert.equal((await calculate(() => order.press('Enter'))).feasible, true);
    await page.locator('#zbo-on').uncheck();
    assert.equal((await calculate(() => page.locator('#btn-calc').click())).feasible, false);
    await page.locator('#zbo-on').check();
    await calculate(() => page.locator('#btn-calc').click());
    const invalid = await plan('invalid');
    assert(invalid.details.some(d => d.message.includes('F')));
    assert(invalid.details.some(d => d.message.includes('2041')));
    assert.equal((await plan('broken')).constraint_checks.filter(c => !c.ok && c.severity === 'hard').length, 12);
    check('plan edits, ZBO, invalid preserves all validation errors, broken 12 violations (current backend)');
    await plan('v3-earth');
    await page.locator('input.ov[data-kind="sources"][data-id="A"][data-field="price"]').fill('7');
    await page.locator('input.ov[data-kind="demand"][data-id="2040"][data-field="total"]').fill('420');
    const edited = await calculate(() => page.locator('#btn-calc').click());
    assert.equal(edited.meta.overrides.sources.A.price, 7);
    assert.equal(edited.meta.overrides.demand['2040'].total, 420);
    assert.equal(Math.round(edited.totals.pv_total_mln), 9282);
    await page.locator('#sources').screenshot({ path: path.join(out, 'case-data.png') });
    for (const format of ['csv', 'xlsx']) {
      const download = page.waitForEvent('download');
      await page.locator(`#btn-${format}`).click();
      await (await download).saveAs(path.join(out, `overrides.${format}`));
    }
    const reset = await calculate(() => page.locator('#btn-reset-data').click());
    assert.deepEqual(reset.meta.overrides, {});
    assert.equal(reset.feasible, true);
    check('case overrides, CSV/XLSX download, reset');
    // Spy without replacing native scroll: verify order, options and actual destination.
    await page.evaluate(() => {
      window.scrollCalls = [];
      const native = Element.prototype.scrollIntoView;
      Element.prototype.scrollIntoView = function(options) {
        window.scrollCalls.push({id: this.id, options, pv: document.querySelector('#summary').innerText});
        return native.call(this, options);
      };
    });
    await page.locator('#init-stock').fill('16');
    await page.locator('#btn-calc-2').scrollIntoViewIfNeeded();
    assert(await page.evaluate(() => scrollY) > 1000);
    const updated = await calculate(() => page.locator('#btn-calc-2').click());
    await page.waitForFunction(() => Math.abs(document.querySelector('#overview').getBoundingClientRect().top - 20) < 2);
    const calls = await page.evaluate(() => window.scrollCalls.filter(c => c.id === 'overview'));
    assert.equal(calls.length, 1);
    assert.equal(calls[0].options.behavior, 'smooth');
    assert(calls[0].pv.includes(updated.totals.pv_total_mln.toLocaleString('ru-RU', {maximumFractionDigits: 0})));
    assert.equal(await page.locator('#init-stock').inputValue(), '16');
    await page.locator('#init-stock').fill('-1');
    await page.locator('#btn-calc-2').scrollIntoViewIfNeeded();
    const before = await page.evaluate(() => { window.scrollCalls = []; return document.querySelector('#btn-calc-2').getBoundingClientRect().top; });
    await calculate(() => page.locator('#btn-calc-2').click(), 400);
    assert(Math.abs(await page.locator('#btn-calc-2').evaluate(el => el.getBoundingClientRect().top) - before) < 2);
    assert.equal(await page.evaluate(() => window.scrollCalls.filter(c => c.id === 'overview').length), 0);
    assert.equal(await page.locator('#calc-error').isVisible(), true);
    await page.locator('#init-stock').fill('15');
    await page.route('**/api/calculate', route => route.fulfill({status: 500, contentType: 'application/json', body: JSON.stringify({error: 'TEST_BACKEND_ERROR', message: 'Тестовая ошибка сервера'})}));
    const failed = page.waitForResponse(r => r.url().endsWith('/api/calculate'));
    await page.locator('#btn-calc-2').click();
    await failed;
    await page.waitForFunction(() => document.querySelector('#calc-error').textContent === 'Тестовая ошибка сервера');
    assert(Math.abs(await page.locator('#btn-calc-2').evaluate(el => el.getBoundingClientRect().top) - before) < 2);
    assert.equal(await page.evaluate(() => window.scrollCalls.filter(c => c.id === 'overview').length), 0);
    await page.unroute('**/api/calculate');
    await calculate(() => page.locator('#btn-calc-2').click());
    await page.waitForFunction(() => Math.abs(document.querySelector('#overview').getBoundingClientRect().top - 20) < 2);
    check('successful bottom calculate scrolls smoothly after render; validation and server errors stay at form');
    await plan('base-v1');
    await page.locator('#plan-id').fill('ui-review-smoke');
    const saved = page.waitForResponse(r => r.url().endsWith('/api/plans') && r.request().method() === 'POST');
    await page.locator('#btn-save').click();
    assert.equal((await saved).status(), 200);
    await page.reload();
    await page.waitForFunction(() => state.result !== null);
    await plan('ui-review-smoke');
    assert.equal(await page.locator('#plan-id').inputValue(), 'ui-review-smoke');
    const jsonDownload = page.waitForEvent('download');
    await page.locator('#btn-plan').click();
    const jsonPath = path.join(out, 'plan.json');
    await (await jsonDownload).saveAs(jsonPath);
    await calculate(() => page.locator('#plan-file').setInputFiles(jsonPath));
    await page.locator('#plan-file').setInputFiles({ name: 'malformed.json', mimeType: 'application/json', buffer: Buffer.from('{') });
    await page.locator('#error:not(.hidden)').waitFor();
    await calculate(() => page.locator('#plan-file').setInputFiles(path.resolve('results/plans/invalid.json')), 400);
    await plan('base-v1');
    assert.equal((await scenario('MANDATORY_STRESS')).feasible, false);
    await plan('stress-response');
    assert.equal((await scenario('MANDATORY_STRESS')).feasible, true);
    check('save/reload, JSON download/upload/errors, legacy plans');
    assert.deepEqual(errors, []);
    check('no uncaught JS or unexpected console errors');
    fs.writeFileSync(path.join(out, 'report.json'), JSON.stringify({ checks: log, errors }, null, 2));
  } finally {
    await browser.close();
    const saved = path.resolve('results/plans/ui-review-smoke.json');
    if (fs.existsSync(saved)) fs.unlinkSync(saved);
  }
})().catch(e => { console.error(e); process.exitCode = 1; });

