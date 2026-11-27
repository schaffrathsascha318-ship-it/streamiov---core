'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const ROOT = path.resolve(__dirname, '../../..');
const COMBINE = path.join(ROOT, 'dist/streamiov-homepage-worker/public/download/combine.js');

function loadCombiner({ subtle = undefined, firstPartBytes = 86540 } = {}) {
  const source = fs.readFileSync(COMBINE, 'utf8');
  const status = { textContent: '' };
  const progress = { textContent: '' };
  let click = null;
  let domReady = null;
  let aborts = 0;
  let closes = 0;
  const button = {
    dataset: { studioStatus: 'status', studioProgress: 'progress' },
    disabled: false,
    addEventListener(type, listener) {
      if (type === 'click') click = listener;
    }
  };
  const writable = {
    write: async () => {},
    close: async () => { closes += 1; },
    abort: async () => { aborts += 1; }
  };
  const sandbox = {
    console,
    Uint8Array,
    Blob: class {
      constructor(chunks) { this.chunks = chunks; }
      async arrayBuffer() {
        const size = this.chunks.reduce((sum, chunk) => sum + chunk.byteLength, 0);
        const bytes = new Uint8Array(size);
        let offset = 0;
        for (const chunk of this.chunks) {
          bytes.set(chunk, offset);
          offset += chunk.byteLength;
        }
        return bytes.buffer;
      }
    },
    crypto: subtle ? { subtle } : { subtle: undefined },
    document: {
      addEventListener(type, listener) {
        if (type === 'DOMContentLoaded') domReady = listener;
      },
      getElementById(id) {
        if (id === 'status') return status;
        if (id === 'progress') return progress;
        return null;
      },
      querySelectorAll: () => [button]
    },
    window: {
      showSaveFilePicker: async () => ({ createWritable: async () => writable })
    },
    fetch: async () => {
      let delivered = false;
      return {
        ok: true,
        status: 200,
        body: {
          getReader: () => ({
            read: async () => {
              if (delivered) return { done: true };
              delivered = true;
              return { done: false, value: new Uint8Array(firstPartBytes) };
            }
          })
        }
      };
    }
  };
  vm.createContext(sandbox);
  vm.runInContext(source, sandbox, { filename: COMBINE });
  domReady();
  return {
    button,
    status,
    progress,
    click: async () => click(),
    counts: () => ({ aborts, closes })
  };
}

test('download combiner fails closed when WebCrypto is unavailable', async () => {
  const combiner = loadCombiner({ subtle: undefined });
  await combiner.click();
  assert.equal(combiner.counts().aborts, 1);
  assert.equal(combiner.counts().closes, 0);
  assert.match(combiner.status.textContent, /Download fehlgeschlagen: SHA-256/);
  assert.doesNotMatch(combiner.status.textContent, /vollständig/);
  assert.equal(combiner.progress.textContent, 'Nicht vollständig');
  assert.equal(combiner.button.disabled, false);
});

test('download combiner rejects a part with the wrong size', async () => {
  const combiner = loadCombiner({ subtle: { digest: async () => new ArrayBuffer(32) }, firstPartBytes: 7 });
  await combiner.click();
  assert.equal(combiner.counts().aborts, 1);
  assert.equal(combiner.counts().closes, 0);
  assert.match(combiner.status.textContent, /Bytes/);
  assert.doesNotMatch(combiner.status.textContent, /vollständig/);
});
