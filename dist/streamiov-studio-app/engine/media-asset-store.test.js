'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const { createMediaAssetStore } = require('./media-asset-store');

test('imports media into a private store and restores the manifest', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'streamiov-media-store-'));
  const source = path.join(root, 'sample.wav');
  const library = path.join(root, 'library');
  await fs.writeFile(source, Buffer.from('RIFF____WAVEfmt data'));
  try {
    const store = createMediaAssetStore({ rootDir: library, now: () => '2026-11-26T00:00:00.000Z' });
    await store.load();
    const asset = await store.importFile(source, 'audio');
    assert.equal(asset.kind, 'audio');
    assert.equal(asset.size, 20);
    assert.match(asset.fileName, /^[a-f0-9-]{36}\.wav$/);
    const resolved = store.resolve(asset.id);
    assert.equal(await fs.readFile(resolved, 'utf8'), 'RIFF____WAVEfmt data');
    const reloaded = createMediaAssetStore({ rootDir: library });
    await reloaded.load();
    assert.deepEqual(reloaded.list(), [asset]);
    assert.equal(await reloaded.remove(asset.id), true);
    assert.deepEqual(reloaded.list(), []);
  } finally {
    await fs.rm(root, { recursive: true, force: true });
  }
});

test('rejects unsupported media and invalid asset ids', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'streamiov-media-invalid-'));
  const source = path.join(root, 'notes.txt');
  await fs.writeFile(source, 'not media');
  try {
    const store = createMediaAssetStore({ rootDir: path.join(root, 'library') });
    await store.load();
    await assert.rejects(() => store.importFile(source));
    await assert.rejects(() => store.importFile(source, 'video'));
    assert.equal(store.resolve('../media-assets.json'), null);
    assert.equal(store.resolve('missing'), null);
  } finally {
    await fs.rm(root, { recursive: true, force: true });
  }
});
