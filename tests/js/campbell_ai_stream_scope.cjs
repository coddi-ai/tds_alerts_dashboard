// Run: node tests/js/campbell_ai_stream_scope.cjs
// Execute the shipped asset with controlled streams, including events after abort.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const requests = [];
const node = {textContent: '', scrollTop: 0, scrollHeight: 0};
const noUpdate = {};
const sandbox = {
  window: {dash_clientside: {no_update: noUpdate}, location: {pathname: '/agents/campbell-ai'}},
  document: {getElementById: () => node},
  AbortController, TextDecoder, Date,
  fetch: (_url, options) => {
    let deliver;
    const reader = {read: () => new Promise(resolve => {deliver = resolve;})};
    requests.push({options, event: event => deliver({done: false,
      value: new TextEncoder().encode('data: ' + JSON.stringify(event) + '\n\n')})});
    return Promise.resolve({ok: true, body: {getReader: () => reader}});
  },
};
vm.runInNewContext(fs.readFileSync(path.join(__dirname,
  '../../dashboard/assets/campbell_ai_stream.js'), 'utf8'), sandbox);
const api = sandbox.window.dash_clientside.campbellAiStream;
const tick = () => new Promise(resolve => setImmediate(resolve));
const pending = id => ({message: 'synthetic', stream: true, session_id: id,
  company_id: 'test', client_message_id: 'message-' + id});

(async () => {
  api.start(pending('old'));
  await tick();
  api.start(null); // Navigation clears pending.
  assert.equal(requests[0].options.signal.aborted, true);
  api.start(pending('active'));
  await tick();
  requests[0].event({type: 'delta', text: 'STALE'});
  await tick();
  assert.equal(node.textContent, '');
  requests[0].event({type: 'done', session_id: 'old', company_id: 'test'});
  await tick();
  assert.equal(api.collect(), noUpdate);
  requests[1].event({type: 'delta', text: 'CURRENT'});
  await tick();
  assert.equal(node.textContent, 'CURRENT');
  requests[1].event({type: 'done', session_id: 'active', company_id: 'test'});
  await tick();
  const result = api.collect();
  assert.equal(result.ok, true);
  assert.equal(result.session_id, 'active');
  assert.equal(result.client_message_id, 'message-active');
  assert.equal(api.collect(), noUpdate);
  api.start(pending('failure'));
  await tick();
  requests[2].event({type: 'error', detail: 'synthetic error'});
  await tick();
  const failure = api.collect();
  assert.equal(failure.ok, false);
  assert.equal(failure.session_id, 'failure');
  assert.equal(failure.company_id, 'test');
  api.stop();
  console.log('PASS: cancellation, stale deltas/done, active delivery, failure scope, one-time collect');
})().catch(error => {console.error(error); process.exitCode = 1;});
