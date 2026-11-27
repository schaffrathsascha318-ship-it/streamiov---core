'use strict';

function redactUrlForLog(value) {
  const raw = String(value ?? '');
  try {
    const url = new URL(raw);
    if (!['file:', 'http:', 'https:'].includes(url.protocol)) return '[invalid-url]';
    url.username = '';
    url.password = '';
    url.search = '';
    url.hash = '';
    return url.toString();
  } catch {
    return '[invalid-url]';
  }
}

module.exports = { redactUrlForLog };
