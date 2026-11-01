'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');

const mainProcess = fs.readFileSync(require.resolve('../main.js'), 'utf8');

test('packaged Studio does not call repository-only Python modules', () => {
  assert.doesNotMatch(mainProcess, /modules\\.broadcast|modules\\.devices|studio\\.modules\\.module_loader/);
  assert.doesNotMatch(mainProcess, /execFileAsync\\(['"]python3['"]/);
});

test('runtime reports compositor, encoder and audio mixer as unfinished', () => {
  assert.match(mainProcess, /compositor: 'not_implemented'/);
  assert.match(mainProcess, /encoder: 'not_implemented'/);
  assert.match(mainProcess, /stage: 'not_implemented'/);
  assert.match(mainProcess, /live_stream_verified: false/);
});
