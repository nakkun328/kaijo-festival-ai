const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync('web/app.js', 'utf8');
const start = source.indexOf('function quickTurnDecision(');
const end = source.indexOf('\nfunction watchVoice()', start);
assert.ok(start >= 0 && end > start);
const quickTurnDecision = vm.runInNewContext(`${source.slice(start, end)}\nquickTurnDecision`);

for (const [text, expected] of [
  ['こんにちは', true],
  ['こんにちは。', true],
  ['ありがとう。', true],
  ['教えて', true],
  ['何について？', true],
  ['今日は疲れた。', true],
  ['大学に行こうと思うけど。', false],
  ['東京に行く予定だったので。', false],
  ['というより。', false],
  ['それについて。', false],
  ['進路を考えていて', false],
  ['進路を考えている', null],
]) {
  assert.equal(quickTurnDecision(text), expected, text);
}
console.log('PASS: complete greetings and questions; hold unfinished clauses despite punctuation');
