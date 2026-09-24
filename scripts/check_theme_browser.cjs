const { chromium } = require('C:/Users/Natsuki/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const assert = require('node:assert/strict');

(async () => {
  const browser = await chromium.launch({channel:'msedge', headless:true});
  const context = await browser.newContext({viewport:{width:390,height:844}});
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  try {
    await page.goto('http://127.0.0.1:8765');
    await page.locator('.theme-panel summary').click();
    await page.locator('#theme-title').fill('検証用の相談');
    await page.locator('#theme-goal').fill('旅行先を決める');
    await page.locator('#theme-options').fill('海・山');
    await page.locator('#theme-open').fill('予算');
    await page.locator('#theme-decisions').fill('来月行く');
    await page.locator('#theme-form button[type=submit]').click();
    await page.getByText('テーマを保存しました。', {exact:true}).waitFor();
    assert.match(await page.locator('#active-theme-label').textContent(), /検証用の相談/);
    await page.reload();
    await page.waitForFunction(() => document.querySelector('#theme-goal').value === '旅行先を決める');
    assert.equal(await page.locator('#theme-goal').inputValue(), '旅行先を決める');
    assert.equal(await page.locator('#theme-open').inputValue(), '予算');
    const other = await browser.newContext();
    const second = await other.newPage();
    await second.goto('http://127.0.0.1:8765');
    await second.locator('#theme-select').waitFor({state:'attached'});
    assert.equal(await second.locator('#theme-select option').count(), 1);
    await other.close();
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth), false);
    page.on('dialog', dialog => dialog.accept());
    await page.locator('.theme-panel summary').click();
    await page.locator('#theme-delete').click();
    await page.getByText('テーマを削除しました。', {exact:true}).waitFor();
    assert.equal(await page.locator('#theme-select option').count(), 1);
    assert.deepEqual(errors, []);
    console.log('PASS: theme UI create/reload/isolation/mobile/delete; no JS errors');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
