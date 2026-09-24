const { chromium, request } = require('C:/Users/Natsuki/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const fs = require('node:fs');
const assert = require('node:assert/strict');
(async () => {
  const api = await request.newContext({baseURL:'http://127.0.0.1:8765'});
  await api.get('/api/bootstrap');
  const response = await api.post('/api/voice', {data:{text:'こんにちは。'}});
  assert.equal(response.status(),200);
  const wav = await response.body();
  // VOICEVOX returns PCM WAV; append silence so continued-speech detection is exercised accurately.
  let offset = 12, dataOffset = -1;
  while (offset + 8 <= wav.length) {
    const size = wav.readUInt32LE(offset+4);
    if (wav.toString('ascii', offset, offset+4) === 'data') { dataOffset = offset; break; }
    offset += 8 + size + (size % 2);
  }
  assert.ok(dataOffset > 0);
  const byteRate = wav.readUInt32LE(28);
  const silence = Buffer.alloc(byteRate * 20);
  const originalSize = wav.readUInt32LE(dataOffset+4);
  const lead = Buffer.alloc(byteRate * 2);
  const fixture = Buffer.concat([wav.subarray(0,dataOffset+8),lead,wav.subarray(dataOffset+8,dataOffset+8+originalSize),silence]);
  fixture.writeUInt32LE(fixture.length-8,4);
  fixture.writeUInt32LE(originalSize+lead.length+silence.length,dataOffset+4);
  const path = 'C:/Codex-AICreating/tmp/daily-voice-fixture.wav';
  fs.writeFileSync(path,fixture);
  await api.dispose();
  const browser = await chromium.launch({channel:'msedge',headless:true,args:[
    '--use-fake-device-for-media-stream','--use-fake-ui-for-media-stream',
    '--use-file-for-fake-audio-capture='+path+'%noloop', '--autoplay-policy=no-user-gesture-required']});
  const context = await browser.newContext({permissions:['microphone']});
  const page = await context.newPage();
  const requests = [];
  const requestTimes = [];
  let startedAt = 0;
  page.on('request',r => {if(r.method()==='POST') { const path=new URL(r.url()).pathname; requests.push(path); if(startedAt && path!='/api/conversation-state') requestTimes.push({path,ms:Date.now()-startedAt}); if(path!='/api/conversation-state') console.log('request',path); }});
  page.on('response', async r => {
    if (new URL(r.url()).pathname === '/api/analyze-turn') {
      try { const data = await r.json(); console.log('recognized',JSON.stringify({text:data.text,complete:data.complete,timings:data.timings})); } catch {}
    }
  });
  try {
    await page.goto('http://127.0.0.1:8765');
    await page.locator('#conversation-start:enabled').waitFor({timeout:30000});
    startedAt = Date.now();
    await page.locator('#conversation-start').click();
    await page.waitForFunction(() => document.querySelectorAll('.message.user').length > 0, null, {timeout:90000});
    const heardMs = Date.now()-startedAt;
    await page.waitForFunction(() => document.querySelectorAll('.message.ai:not(.thinking)').length >= 2, null, {timeout:180000});
    const answerMs = Date.now()-startedAt;
    await page.waitForFunction(() => document.querySelector('#voice-state').textContent.includes('話しています'), null, {timeout:180000});
    const speechMs = Date.now()-startedAt;
    await page.waitForFunction(() => document.querySelector('#live-transcript-hint').textContent.includes('次の発言'), null, {timeout:180000});
    await page.locator('#conversation-stop').click();
    await page.getByText('対話を停止しました',{exact:true}).waitFor();
    assert.ok(requests.includes('/api/analyze-turn'));
    assert.ok(requests.includes('/api/chat-stream'));
    assert.ok(requests.includes('/api/voice'));
    await page.locator('#message:enabled').waitFor();
    const stageDurations = await page.locator('[data-duration]').evaluateAll(items =>
      Object.fromEntries(items.map(item => [item.dataset.duration, item.textContent.trim()])));
    console.log('LATENCY', JSON.stringify({heardMs,answerMs,speechMs,requestTimes,stageDurations}));
    console.log('PASS: fake microphone -> transcription -> automatic chat -> voice playback -> listen again -> stop');
    await page.locator('#reset').click();
  } finally { await browser.close(); }
})().catch(error => {console.error(error);process.exitCode=1;});
