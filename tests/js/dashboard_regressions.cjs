// Node-only source tests. No browser, network, external account, or order interaction.
const fs = require('node:fs');
const vm = require('node:vm');
const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const root = path.resolve(__dirname, '../..');

test('stock selection failure remains visible after the next countdown tick', async () => {
  const elements = new Map();
  const timers = [];
  function element(selector) {
    if (!elements.has(selector)) elements.set(selector, {
      value: 'ALL', innerHTML: '', textContent: '',
      addEventListener() {}, scrollIntoView() {}, querySelectorAll() { return []; },
      classList: { add() {} },
    });
    return elements.get(selector);
  }
  const context = vm.createContext({
    document: { querySelector: element }, AbortController, Date, console,
    setTimeout() { return 1; }, clearTimeout() {},
    setInterval(fn, ms) { timers.push({fn, ms}); },
    fetch: async (url) => {
      if (url.endsWith('/scanner')) return { ok: true, json: async () => ({results: []}) };
      if (url.includes('/NVDA/')) return { ok: false, json: async () => ({reason: 'Provider unavailable'}) };
      return {ok: true, json: async () => ({symbol: 'AAPL', company_name: 'Apple', analysis: {setup_state: 'NO_TRADE', decision: 'NO_TRADE'}})};
    },
  });
  vm.runInContext(fs.readFileSync(path.join(root, 'app/stocks.js'), 'utf8'), context);
  await vm.runInContext("analyse('AAPL')", context);
  await vm.runInContext("analyse('NVDA')", context);
  assert.match(element('#analysisPanel').innerHTML, /NVDA/);
  timers.find(timer => timer.ms === 1000).fn();
  assert.match(element('#analysisPanel').innerHTML, /NVDA/, 'one-second timer restored the previous AAPL analysis');
  const pending = new Map();
  context.fetch = url => new Promise(resolve => pending.set(url, resolve));
  const older = vm.runInContext("analyse('AAPL')", context);
  const newer = vm.runInContext("analyse('NVDA')", context);
  const respond = symbol => pending.get(`/api/stocks/${symbol}/analysis`)({ok: true, json: async () => ({symbol, analysis: {setup_state: 'NO_TRADE'}})});
  respond('NVDA'); await newer;
  respond('AAPL'); await older;
  timers.find(timer => timer.ms === 1000).fn();
  assert.match(element('#analysisPanel').innerHTML, /NVDA/, 'late response overwrote newer selection');
});

test('signal sync preserves the actual HTTP error', async () => {
  const source = fs.readFileSync(path.join(root, 'app/app.js'), 'utf8');
  const begin = source.indexOf('async function persistSignalRecord(entry)');
  const end = source.indexOf('\nfunction ', begin + 1);
  const observed = [];
  const context = vm.createContext({
    currentUser: {authenticated: true},
    jsonPost: async () => ({ok: false, json: async () => ({error: 'Session expired'})}),
    addAuditEvent: (...args) => observed.push(args),
    renderPerformanceSummary() {}, console,
  });
  const helperStart = source.indexOf("async function responseError(response)");
  vm.runInContext(source.slice(helperStart, begin) + source.slice(begin, end), context);
  await vm.runInContext("persistSignalRecord({id: 'local-test'})", context);
  assert.ok(observed.flat().some(value => String(value).includes('Session expired')), JSON.stringify(observed));
});


test('HTTP error parser handles non-JSON error bodies', async () => {
  const source = fs.readFileSync(path.join(root, 'app/app.js'), 'utf8');
  const begin = source.indexOf('async function responseError(response)');
  const end = source.indexOf('async function persistSignalRecord', begin);
  const context = vm.createContext({response: {status: 503, json: async () => { throw Error('not JSON'); }}});
  vm.runInContext(source.slice(begin, end), context);
  assert.equal(await vm.runInContext('responseError(response)', context), 'Request failed (HTTP 503)');
});
