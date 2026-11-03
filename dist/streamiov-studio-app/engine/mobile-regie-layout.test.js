'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

test('mobile Regie markup places the content stage before the Studio controls', () => {
  const html = fs.readFileSync(path.join(__dirname, '..', 'regie-v2.html'), 'utf8');
  const content = html.indexOf('id="mobile-content-stage"');
  const toggle = html.indexOf('id="mobile-regie-toggle"');
  const regie = html.indexOf('<main id="studio-regie">');
  assert.ok(content >= 0 && toggle > content && regie > toggle);
  assert.match(html, /main\.mobile-regie-collapsed\{display:none\}/);
  assert.match(html, /INHALT BLEIBT OBEN · REGIE DARUNTER/);
});

test('mobile layout provides a collapsible Regie control with accessible state', () => {
  const html = fs.readFileSync(path.join(__dirname, '..', 'regie-v2.html'), 'utf8');
  assert.match(html, /aria-controls="studio-regie"/);
  assert.match(html, /aria-expanded="true"/);
  assert.match(html, /REGIE \/ STUDIO EINBLENDEN/);
});
