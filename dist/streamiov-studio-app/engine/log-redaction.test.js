'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { redactUrlForLog } = require('./log-redaction');

test('URL trace logs drop credentials, query strings, and fragments', () => {
  const redacted = redactUrlForLog(
    'http://user:secret@localhost:8765/api/v1/platforms/twitch/callback?code=abc123&state=xyz#token'
  );
  assert.equal(redacted, 'http://localhost:8765/api/v1/platforms/twitch/callback');
  assert.equal(redacted.includes('secret'), false);
  assert.equal(redacted.includes('abc123'), false);
  assert.equal(redacted.includes('xyz'), false);
  assert.equal(redacted.includes('token'), false);
});

test('local studio file URLs keep their path but lose injected parameters', () => {
  assert.equal(
    redactUrlForLog('file:///C:/Studio/regie-v2.html?access_token=abc'),
    'file:///C:/Studio/regie-v2.html'
  );
});

test('unparseable URLs never reach logs verbatim', () => {
  assert.equal(redactUrlForLog('javascript:alert(1)'), '[invalid-url]');
  assert.equal(redactUrlForLog(''), '[invalid-url]');
  assert.equal(redactUrlForLog(undefined), '[invalid-url]');
});
