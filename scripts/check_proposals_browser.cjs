const { chromium } = require('C:/Users/Natsuki/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const assert = require('node:assert/strict');

(async () => {
  const browser = await chromium.launch({channel:'msedge', headless:true});
  const page = await browser.newPage({viewport:{width:390,height:844}});
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  try {
    await page.goto('http://127.0.0.1:8766');
    await page.waitForFunction(() => document.querySelector('#provider').options.length > 0 &&
      !document.querySelector('#composer button').disabled, {timeout:30000});
    await page.locator('#message').fill('私はギターが好き。');
    await page.locator('#composer button').click();
    await page.locator('#memory-proposal').waitFor({timeout:60000});
    assert.equal(await page.locator('#memory-list textarea').count(), 0);
    await page.locator('#memory-proposal-content').fill('ギターを練習している');
    await page.locator('#memory-proposal-save').click();
    await page.waitForFunction(() => document.querySelector('#memory-proposal').hidden);
    assert.equal(await page.locator('#memory-list textarea').first().inputValue(), 'ギターを練習している');
    await page.locator('#message:enabled').fill('私は月を見るのが好き。');
    await page.locator('#composer button').click();
    await page.locator('#memory-proposal').waitFor();
    assert.match(await page.locator('.message.ai').last().locator('p').textContent(), /これ、覚えておく？/);
    await page.locator('#message:enabled').fill('うん。');
    await page.locator('#composer button').click();
    await page.waitForFunction(() => document.querySelector('#memory-proposal').hidden);
    assert.equal(await page.locator('#memory-list textarea').count(), 2);
    await page.locator('#message:enabled').fill('私は大阪の街が好き。');
    await page.locator('#composer button').click();
    await page.locator('#memory-proposal').waitFor();
    await page.locator('#message:enabled').fill('いや、東京の街のほうが好きだった。');
    await page.locator('#composer button').click();
    await page.waitForFunction(() => document.querySelector('#memory-proposal').hidden);
    assert.equal(await page.locator('#memory-list textarea').count(), 2);
    await page.locator('#message:enabled').fill('私は映画を見るのが好き。');
    await page.locator('#composer button').click();
    await page.locator('#memory-proposal').waitFor();
    await page.locator('#message:enabled').fill('今はいい。');
    await page.locator('#composer button').click();
    await page.waitForFunction(() => document.querySelector('#memory-proposal').hidden);
    assert.equal(await page.locator('#memory-list textarea').count(), 2);
    await page.locator('#message').fill('進路について考えたい。大学か就職か迷っていて、目的は自分に合う学び方を決めること。費用が未解決。');
    await page.locator('#composer button').click();
    await page.locator('.message.ai').last().locator('p').waitFor();
    await page.locator('.theme-panel summary').click();
    await page.locator('#theme-draft').click();
    await page.getByText('下書きを表示しました。内容を確認・修正し、「テーマを保存」で確定してください。', {exact:true}).waitFor({timeout:60000});
    assert.ok((await page.locator('#theme-title').inputValue()).length > 0);
    assert.equal(await page.locator('#theme-select option').count(), 1);
    await page.locator('#theme-form button[type=submit]').click();
    await page.getByText('テーマを保存しました。', {exact:true}).waitFor();
    assert.equal(await page.locator('#theme-select option').count(), 2);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    assert.deepEqual(errors, []);
    console.log('PASS: memory proposal yes/no and correction withdrawal, theme draft review/save, mobile width, no JS errors');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
