'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs/promises');
const fsSync = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { EventEmitter } = require('node:events');
const {
  UPDATE_MANIFEST_URL,
  UPDATE_MANIFEST_SIGNATURE_URL,
  RELEASE_BASE_URL,
  UPDATE_PUBLIC_KEY_PEM,
  StreamiovAppUpdater,
  compareVersions,
  parseUpdateManifest,
  publicKeyFingerprint,
  releaseAssetUrl,
  verifyManifestSignature
} = require('./app-updater.js');

function createKeys() {
  return crypto.generateKeyPairSync('ed25519');
}

function exportPublicKey(keyPair) {
  return keyPair.publicKey.export({ type: 'spki', format: 'pem' });
}

function makeResponse(bytes, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: { get: (name) => name === 'content-length' ? String(bytes.length) : null },
    arrayBuffer: async () => Uint8Array.from(bytes).buffer
  };
}

function spawnedChild() {
  const child = new EventEmitter();
  child.pid = 4242;
  child.unref = () => {};
  setImmediate(() => child.emit('spawn'));
  return child;
}

function makeFixture({ version = '1.0.5', currentVersion = '1.0.4', filename = 'Streamiov.Studio.Setup.1.0.5-x64.exe', assetBytes = Buffer.from('test-installer-bytes'), installMode = 'silent', keys = createKeys(), signingKeys = keys, target = 'win32-x64', platform = 'win32', arch = 'x64', packaged = true, isUpdateAllowed = () => true, spawnImpl = spawnedChild, corruptAsset = false, tamperSignature = false } = {}) {
  const manifest = {
    format: 'streamiov-studio-update-v1',
    version,
    releasedAt: '2026-11-25T00:00:00.000Z',
    notes: 'Testupdate',
    assets: {
      [target]: {
        filename,
        sha256: crypto.createHash('sha256').update(assetBytes).digest('hex'),
        size: assetBytes.length,
        installMode
      }
    }
  };
  const manifestBytes = Buffer.from(JSON.stringify(manifest, null, 2) + '\n');
  let signature = crypto.sign(null, manifestBytes, signingKeys.privateKey).toString('base64') + '\n';
  if (tamperSignature) signature = Buffer.from(signature, 'ascii').toString('base64').slice(0, -4) + 'AAAA\n';
  const calls = [];
  const deliveredAsset = corruptAsset ? Buffer.from(assetBytes).map((byte, index) => index === 0 ? byte ^ 1 : byte) : assetBytes;
  const fetchImpl = async (url) => {
    calls.push(url);
    if (url === UPDATE_MANIFEST_URL) return makeResponse(manifestBytes);
    if (url === UPDATE_MANIFEST_SIGNATURE_URL) return makeResponse(Buffer.from(signature, 'ascii'));
    if (url === releaseAssetUrl(version, filename)) return makeResponse(deliveredAsset);
    return makeResponse(Buffer.from('not found'), 404);
  };
  const userDataDir = fsSync.mkdtempSync(path.join(os.tmpdir(), 'streamiov-update-test-'));
  const updater = new StreamiovAppUpdater({
    currentVersion,
    userDataDir,
    platform,
    arch,
    packaged,
    publicKeyPem: exportPublicKey(keys),
    trustedPublicKeyPem: exportPublicKey(keys),
    allowUntrustedTestKey: true,
    fetchImpl,
    spawnImpl,
    isUpdateAllowed
  });
  return { updater, userDataDir, calls, manifestBytes, signature, assetBytes, filename, version };
}

async function cleanup(t, fixture) {
  t.after(async () => fs.rm(fixture.userDataDir, { recursive: true, force: true }));
}

test('version comparison handles numeric core versions and prereleases', () => {
  assert.equal(compareVersions('1.0.5', '1.0.4'), 1);
  assert.equal(compareVersions('1.0.4', '1.0.4'), 0);
  assert.equal(compareVersions('1.0.3', '1.0.4'), -1);
  assert.equal(compareVersions('2.0.0', '1.99.99'), 1);
  assert.equal(compareVersions('1.1.0', '1.0.9'), 1);
  assert.equal(compareVersions('1.1.0-rc.1', '1.1.0'), -1);
});

test('pinned public key fingerprint stays stable', () => {
  assert.equal(publicKeyFingerprint(UPDATE_PUBLIC_KEY_PEM), '2c3de4b60d60cf4c7fa19ac3378a504706f79960978dfb610d9660bc10aeb09e');
});

test('manifest parsing rejects unsupported formats and insecure assets', () => {
  const keys = createKeys();
  const valid = {
    format: 'streamiov-studio-update-v1',
    version: '1.0.5',
    notes: 'Test',
    assets: {
      'win32-x64': {
        filename: 'Streamiov.Studio.Setup.1.0.5-x64.exe',
        sha256: 'a'.repeat(64),
        size: 1024,
        installMode: 'silent'
      }
    }
  };
  assert.equal(parseUpdateManifest(Buffer.from(JSON.stringify(valid)), '1.0.4').version, '1.0.5');
  assert.throws(() => parseUpdateManifest(Buffer.from(JSON.stringify({ ...valid, format: 'other' })), '1.0.4'));
  assert.throws(() => parseUpdateManifest(Buffer.from(JSON.stringify({
    ...valid,
    assets: { 'win32-x64': { ...valid.assets['win32-x64'], filename: '../bad.exe' } }
  })), '1.0.4'));
  const bytes = Buffer.from(JSON.stringify(valid));
  const signature = crypto.sign(null, bytes, keys.privateKey).toString('base64') + '\n';
  assert.throws(() => verifyManifestSignature(bytes, signature, exportPublicKey(createKeys()), exportPublicKey(keys)));
});

test('signed update is downloaded, verified, staged and installed from a fixed URL', async (t) => {
  const spawnCalls = [];
  const spawnImpl = (file, args, options) => {
    spawnCalls.push({ file, args, options });
    const child = new EventEmitter();
    child.pid = 4242;
    child.unref = () => {};
    setImmediate(() => child.emit('spawn'));
    return child;
  };
  const fixture = makeFixture({ spawnImpl });
  await cleanup(t, fixture);
  const check = await fixture.updater.check();
  assert.equal(check.ok, true);
  assert.equal(check.available, true);
  assert.equal(check.latestVersion, '1.0.5');
  const prepare = await fixture.updater.prepare();
  assert.equal(prepare.ok, true);
  assert.equal(prepare.prepared, true);
  const staged = path.join(fixture.userDataDir, 'updates', 'staged', '1.0.5', fixture.filename);
  assert.equal((await fs.readFile(staged)).toString(), fixture.assetBytes.toString());
  const install = await fixture.updater.install();
  assert.equal(install.ok, true);
  assert.equal(install.status, 'installer_started');
  assert.equal(install.restartRequired, true);
  assert.equal(spawnCalls.length, 1);
  assert.equal(spawnCalls[0].args[0], '/S');
  assert.ok(fixture.calls.includes(RELEASE_BASE_URL + 'studio-v1.0.5/' + fixture.filename));
  assert.equal(fixture.updater.status().state, 'installer_started');
});

test('invalid signature blocks any asset download', async (t) => {
  const signingKeys = createKeys();
  const fixture = makeFixture({ signingKeys, tamperSignature: true });
  await cleanup(t, fixture);
  const result = await fixture.updater.check();
  assert.equal(result.ok, false);
  assert.equal(result.error.code, 'invalid_signature_encoding');
  assert.equal(fixture.calls.length, 2);
  assert.equal(fixture.updater.status().state, 'error');
});

test('wrong signing key is rejected even when signature encoding is valid', async (t) => {
  const signingKeys = createKeys();
  const fixture = makeFixture({ signingKeys });
  await cleanup(t, fixture);
  const result = await fixture.updater.check();
  assert.equal(result.ok, false);
  assert.equal(result.error.code, 'invalid_update_signature');
  assert.equal(fixture.calls.length, 2);
});

test('corrupted download fails closed and restores previous state', async (t) => {
  const fixture = makeFixture({ corruptAsset: true });
  await cleanup(t, fixture);
  const result = await fixture.updater.prepare();
  assert.equal(result.ok, false);
  assert.equal(result.error.code, 'sha256_mismatch');
  assert.equal(fixture.updater.status().state, 'rolled_back');
  assert.deepEqual(fixture.updater.status().lastError, { code: 'sha256_mismatch', message: result.error.message });
  const stageDir = path.join(fixture.userDataDir, 'updates', 'staged', '1.0.5');
  await assert.rejects(() => fs.stat(stageDir));
});

test('installer launch failure rolls back to the known good state', async (t) => {
  const spawnImpl = () => {
    const child = new EventEmitter();
    child.pid = 4243;
    child.unref = () => {};
    setImmediate(() => child.emit('error', new Error('installer blocked')));
    return child;
  };
  const fixture = makeFixture({ spawnImpl });
  await cleanup(t, fixture);
  await fixture.updater.check();
  await fixture.updater.prepare();
  const result = await fixture.updater.install();
  assert.equal(result.ok, false);
  assert.equal(result.error.code, 'installer_launch_failed');
  assert.equal(fixture.updater.status().state, 'rolled_back');
  assert.equal(fixture.updater.status().staged, false);
  const stageDir = path.join(fixture.userDataDir, 'updates', 'staged', '1.0.5');
  await assert.rejects(() => fs.stat(stageDir));
});

test('equal or older versions are not downloaded', async (t) => {
  const fixture = makeFixture({ version: '1.0.4', currentVersion: '1.0.4' });
  await cleanup(t, fixture);
  const result = await fixture.updater.check();
  assert.equal(result.ok, true);
  assert.equal(result.available, false);
  assert.equal(fixture.calls.length, 2);
  const prepared = await fixture.updater.prepare();
  assert.equal(prepared.ok, true);
  assert.equal(prepared.reason, 'no_update_available');
  assert.equal(fixture.calls.length, 4);
  assert.equal(fixture.calls.some((url) => url.startsWith(RELEASE_BASE_URL)), false);
});

test('active stream blocks preparation before any asset download', async (t) => {
  const fixture = makeFixture({ isUpdateAllowed: () => false });
  await cleanup(t, fixture);
  const result = await fixture.updater.prepare();
  assert.equal(result.ok, false);
  assert.equal(result.error.code, 'update_blocked_by_active_stream');
  assert.equal(fixture.calls.length, 2);
});

test('manual Linux package reports a fixed release page without spawning an installer', async (t) => {
  const spawnImpl = () => { throw new Error('must not spawn'); };
  const fixture = makeFixture({
    filename: 'streamiov-studio_1.0.5_amd64.deb',
    installMode: 'manual',
    target: 'linux-x64',
    platform: 'linux',
    arch: 'x64',
    spawnImpl
  });
  await cleanup(t, fixture);
  await fixture.updater.check();
  await fixture.updater.prepare();
  const result = await fixture.updater.install();
  assert.equal(result.ok, true);
  assert.equal(result.status, 'manual_required');
  assert.equal(result.releaseUrl, 'https://github.com/schaffrathsascha318-ship-it/streamiov---core/releases/tag/studio-v1.0.5');
  assert.equal(fixture.updater.status().requiresRestart, false);
});

test('interrupted staged update is recovered and staged files are removed', async (t) => {
  const fixture = makeFixture();
  await cleanup(t, fixture);
  const statePath = path.join(fixture.userDataDir, 'updates', 'update-state.json');
  const stageDir = path.join(fixture.userDataDir, 'updates', 'staged', '1.0.5');
  await fs.mkdir(stageDir, { recursive: true });
  await fs.writeFile(path.join(stageDir, fixture.filename), 'partial', { mode: 0o600 });
  await fs.writeFile(statePath, JSON.stringify({
    status: 'downloading',
    currentVersion: '1.0.4',
    latestVersion: '1.0.5',
    notes: 'Testupdate',
    asset: { filename: fixture.filename, sha256: 'a'.repeat(64), size: 7, installMode: 'silent' },
    staged: false,
    installMode: 'silent',
    requiresRestart: false,
    lastError: null,
    updatedAt: '2026-11-25T00:00:00.000Z'
  }));
  const status = await fixture.updater.recover();
  assert.equal(status.state, 'rolled_back');
  assert.equal(status.lastError.code, 'interrupted_update_recovered');
  assert.equal(status.staged, false);
  await assert.rejects(() => fs.stat(path.join(stageDir, fixture.filename)));
});

test('manipulated staged state cannot spawn a path outside staging', async (t) => {
  const spawnCalls = [];
  const spawnImpl = (file) => {
    spawnCalls.push(file);
    const child = new EventEmitter();
    child.pid = 4244;
    child.unref = () => {};
    setImmediate(() => child.emit('spawn'));
    return child;
  };
  const fixture = makeFixture({ spawnImpl });
  await cleanup(t, fixture);
  fixture.updater.state = {
    ...fixture.updater.state,
    status: 'staged',
    latestVersion: '1.0.5',
    staged: true,
    installMode: 'silent',
    asset: {
      filename: '../../../evil.exe',
      sha256: 'a'.repeat(64),
      size: 1,
      installMode: 'silent'
    }
  };
  const result = await fixture.updater.install();
  assert.equal(result.ok, false);
  assert.equal(result.error.code, 'invalid_manifest_asset');
  assert.equal(spawnCalls.length, 0);
  assert.equal(fixture.calls.length, 0);
  assert.equal(fixture.updater.status().state, 'error');
});

test('recover discards a stored state with an unsafe asset filename', async (t) => {
  const fixture = makeFixture();
  await cleanup(t, fixture);
  const statePath = path.join(fixture.userDataDir, 'updates', 'update-state.json');
  const stageRoot = path.join(fixture.userDataDir, 'updates', 'staged');
  await fs.mkdir(stageRoot, { recursive: true });
  await fs.writeFile(statePath, JSON.stringify({
    status: 'staged',
    currentVersion: '1.0.4',
    latestVersion: '1.0.5',
    notes: 'Testupdate',
    staged: true,
    installMode: 'silent',
    requiresRestart: false,
    lastError: null,
    updatedAt: '2026-11-25T00:00:00.000Z',
    asset: {
      filename: '../evil.exe',
      sha256: 'a'.repeat(64),
      size: 1,
      installMode: 'silent'
    }
  }));
  const status = await fixture.updater.recover();
  assert.equal(status.state, 'rolled_back');
  assert.equal(status.lastError.code, 'invalid_update_state_recovered');
  assert.equal(status.staged, false);
  await assert.rejects(() => fs.stat(path.join(fixture.userDataDir, 'evil.exe')));
});

test('restart after confirmed newer version clears installer state', async (t) => {
  const keys = createKeys();
  const userDataDir = fsSync.mkdtempSync(path.join(os.tmpdir(), 'streamiov-update-test-'));
  t.after(async () => fs.rm(userDataDir, { recursive: true, force: true }));
  const statePath = path.join(userDataDir, 'updates', 'update-state.json');
  await fs.mkdir(path.dirname(statePath), { recursive: true });
  await fs.writeFile(statePath, JSON.stringify({
    status: 'installer_started',
    currentVersion: '1.0.4',
    latestVersion: '1.0.5',
    notes: 'Testupdate',
    asset: {
      filename: 'Streamiov.Studio.Setup.1.0.5-x64.exe',
      sha256: 'a'.repeat(64),
      size: 1,
      installMode: 'silent'
    },
    staged: true,
    installMode: 'silent',
    requiresRestart: true,
    lastError: null,
    updatedAt: '2026-11-25T00:00:00.000Z'
  }));
  const updater = new StreamiovAppUpdater({
    currentVersion: '1.0.5',
    userDataDir,
    platform: 'win32',
    arch: 'x64',
    publicKeyPem: exportPublicKey(keys),
    trustedPublicKeyPem: exportPublicKey(keys),
    allowUntrustedTestKey: true,
    fetchImpl: async () => makeResponse(Buffer.from('unused'))
  });
  const status = await updater.recover();
  assert.equal(status.state, 'idle');
  assert.equal(status.requiresRestart, false);
  assert.equal(status.staged, false);
});

test('constructor rejects a caller-supplied untrusted update key', async (t) => {
  const keys = createKeys();
  const userDataDir = fsSync.mkdtempSync(path.join(os.tmpdir(), 'streamiov-update-test-'));
  t.after(() => fsSync.rmSync(userDataDir, { recursive: true, force: true }));
  assert.throws(() => new StreamiovAppUpdater({
    currentVersion: '1.0.4',
    userDataDir,
    platform: 'win32',
    arch: 'x64',
    publicKeyPem: exportPublicKey(keys),
    trustedPublicKeyPem: exportPublicKey(keys),
    fetchImpl: async () => makeResponse(Buffer.from('unused'))
  }), (error) => error.code === 'untrusted_update_key');
});

test('installer launch fails closed when spawn is never confirmed', async (t) => {
  const spawnImpl = () => {
    const child = new EventEmitter();
    child.pid = 7777;
    child.unref = () => {};
    return child;
  };
  const fixture = makeFixture({ spawnImpl });
  await cleanup(t, fixture);
  await fixture.updater.prepare();
  const result = await fixture.updater.install();
  assert.equal(result.ok, false);
  assert.equal(result.error.code, 'installer_launch_timeout');
  assert.equal(fixture.updater.status().state, 'rolled_back');
  assert.equal(fixture.updater.status().staged, false);
});

test('clearError releases a wedged installer_started state', async (t) => {
  const fixture = makeFixture();
  await cleanup(t, fixture);
  const updatesDir = path.join(fixture.userDataDir, 'updates');
  const statePath = path.join(updatesDir, 'update-state.json');
  await fs.mkdir(path.join(updatesDir, 'staged', '1.0.5'), { recursive: true });
  await fs.writeFile(statePath, JSON.stringify({
    status: 'installer_started',
    currentVersion: '1.0.4',
    latestVersion: '1.0.5',
    notes: 'Testupdate',
    asset: {
      filename: fixture.filename,
      sha256: 'a'.repeat(64),
      size: 1,
      installMode: 'silent'
    },
    staged: true,
    installMode: 'silent',
    requiresRestart: true,
    lastError: null,
    updatedAt: '2026-11-25T00:00:00.000Z'
  }));

  const recovered = await fixture.updater.recover();
  assert.equal(recovered.state, 'installer_started');
  const cleared = await fixture.updater.clearError();
  assert.equal(cleared.state, 'idle');
  assert.equal(cleared.staged, false);
  assert.equal(cleared.latestVersion, null);
  await assert.rejects(() => fs.stat(path.join(updatesDir, 'staged', '1.0.5')));
  const checked = await fixture.updater.check();
  assert.equal(checked.ok, true);
});

test('tampered previous state cannot inject a release version or asset', async (t) => {
  const fixture = makeFixture({ corruptAsset: true });
  await cleanup(t, fixture);
  const previousPath = path.join(fixture.userDataDir, 'updates', 'update-state.previous.json');
  const baseFetch = fixture.updater.fetchImpl;
  fixture.updater.fetchImpl = async (url, options) => {
    if (url === releaseAssetUrl(fixture.version, fixture.filename)) {
      await fs.writeFile(previousPath, JSON.stringify({
        status: 'idle',
        currentVersion: '1.0.4',
        latestVersion: '9.9.9',
        notes: 'injected',
        asset: {
          filename: '../evil.exe',
          sha256: 'a'.repeat(64),
          size: 1,
          installMode: 'silent'
        },
        staged: false,
        installMode: null,
        requiresRestart: false,
        lastError: null,
        updatedAt: '2026-11-25T00:00:00.000Z'
      }));
    }
    return baseFetch(url, options);
  };

  const result = await fixture.updater.prepare();
  assert.equal(result.ok, false);
  const status = fixture.updater.status();
  assert.equal(status.state, 'rolled_back');
  assert.equal(status.latestVersion, null);
  assert.equal(status.asset, null);
  assert.equal(status.notes, '');
});
