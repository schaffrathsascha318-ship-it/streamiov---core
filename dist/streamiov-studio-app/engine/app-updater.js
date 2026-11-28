'use strict';

const crypto = require('node:crypto');
const fsPromises = require('node:fs/promises');
const nodePath = require('node:path');
const { spawn } = require('node:child_process');

const UPDATE_MANIFEST_URL = 'https://streamiov.pages.dev/downloads/studio-update.json';
const UPDATE_MANIFEST_SIGNATURE_URL = UPDATE_MANIFEST_URL + '.sig';
const RELEASE_BASE_URL = 'https://github.com/schaffrathsascha318-ship-it/streamiov---core/releases/download/';
const RELEASE_TAG_URL = 'https://github.com/schaffrathsascha318-ship-it/streamiov---core/releases/tag/';
const UPDATE_PUBLIC_KEY_PEM = `-----BEGIN PUBLIC KEY-----
MCowBQYDK2VwAyEAc8aQcJQE7RfiZMb9AmzBYpirWNXDO2OKjY63+vb/Whg=
-----END PUBLIC KEY-----`;

const MAX_MANIFEST_BYTES = 256 * 1024;
const MAX_SIGNATURE_BYTES = 512;
const MAX_ASSET_BYTES = 512 * 1024 * 1024;
const MAX_NOTES_CHARS = 5000;
const SUPPORTED_TARGETS = new Set(['win32-x64', 'win32-arm64', 'linux-x64', 'linux-arm64', 'darwin-x64', 'darwin-arm64']);
const SAFE_FILENAME = /^[A-Za-z0-9][A-Za-z0-9._-]{0,180}$/;
const VERSION_PATTERN = /^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$/;
const BUSY_STATES = new Set(['checking', 'downloading', 'installing', 'installer_started']);
const ALLOWED_STATES = new Set(['idle', 'checking', 'update_available', 'downloading', 'staged', 'installing', 'installer_started', 'manual_required', 'unsupported', 'rolled_back', 'error']);

class UpdateError extends Error {
  constructor(code, message, details = {}) {
    super(message);
    this.name = 'UpdateError';
    this.code = code;
    Object.assign(this, details);
  }
}

function updateFailure(error) {
  if (error instanceof UpdateError) {
    return { code: error.code, message: error.message };
  }
  return { code: 'update_failed', message: String(error && error.message ? error.message : error).slice(0, 300) };
}

function normalizePublicKey(pem) {
  return String(pem || '').trim().split(/\r?\n/).map((line) => line.trim()).join('\n');
}

function publicKeyFingerprint(pem) {
  const key = crypto.createPublicKey(normalizePublicKey(pem));
  if (key.asymmetricKeyType !== 'ed25519') {
    throw new UpdateError('unsupported_update_key', 'Der Update-Schlüssel ist kein Ed25519-Schlüssel.');
  }
  return crypto.createHash('sha256').update(key.export({ type: 'spki', format: 'der' })).digest('hex');
}

function parseVersion(value) {
  if (typeof value !== 'string' || !VERSION_PATTERN.test(value)) {
    throw new UpdateError('invalid_version', 'Die Versionsnummer hat ein ungültiges Format.');
  }
  const [core, prerelease] = value.split('-', 2);
  const parts = core.split('.').map(Number);
  if (parts.length !== 3 || parts.some((part) => !Number.isSafeInteger(part))) {
    throw new UpdateError('invalid_version', 'Die Versionsnummer hat ein ungültiges Format.');
  }
  return { text: value, parts, prerelease: prerelease || '' };
}

function compareVersions(left, right) {
  const a = parseVersion(left);
  const b = parseVersion(right);
  for (let index = 0; index < 3; index += 1) {
    if (a.parts[index] !== b.parts[index]) return a.parts[index] < b.parts[index] ? -1 : 1;
  }
  if (a.prerelease === b.prerelease) return 0;
  if (!a.prerelease) return 1;
  if (!b.prerelease) return -1;
  return a.prerelease < b.prerelease ? -1 : 1;
}

function verifyManifestSignature(manifestBytes, signatureBytes, publicKeyPem = UPDATE_PUBLIC_KEY_PEM, trustedPublicKeyPem = UPDATE_PUBLIC_KEY_PEM, allowUntrustedTestKey = false) {
  if (normalizePublicKey(publicKeyPem) !== normalizePublicKey(trustedPublicKeyPem)) {
    throw new UpdateError('untrusted_update_key', 'Der Update-Schlüssel entspricht nicht dem fest verankerten Schlüssel.');
  }
  if (!allowUntrustedTestKey && normalizePublicKey(trustedPublicKeyPem) !== normalizePublicKey(UPDATE_PUBLIC_KEY_PEM)) {
    throw new UpdateError('untrusted_update_key', 'Der Update-Schlüssel entspricht nicht dem fest verankerten Schlüssel.');
  }
  const signatureText = Buffer.from(signatureBytes).toString('ascii').trim();
  if (!/^[A-Za-z0-9+/]{86}==$/.test(signatureText)) {
    throw new UpdateError('invalid_signature_encoding', 'Die Update-Signatur hat kein gültiges Ed25519-Format.');
  }
  const signature = Buffer.from(signatureText, 'base64');
  if (signature.length !== 64 || signature.toString('base64') !== signatureText) {
    throw new UpdateError('invalid_signature_encoding', 'Die Update-Signatur ist keine kanonische Base64-Kodierung.');
  }
  const key = crypto.createPublicKey(normalizePublicKey(publicKeyPem));
  let verified = false;
  try {
    verified = crypto.verify(null, Buffer.from(manifestBytes), key, signature);
  } catch (error) {
    throw new UpdateError('signature_verification_failed', String(error && error.message ? error.message : error));
  }
  if (!verified) {
    throw new UpdateError('invalid_update_signature', 'Die Update-Signatur passt nicht zum Manifest.');
  }
}

function normalizeAsset(candidate) {
  if (!candidate || typeof candidate !== 'object' || Array.isArray(candidate)) {
    throw new UpdateError('invalid_manifest_asset', 'Ein Update-Asset hat ein ungültiges Format.');
  }
  if (typeof candidate.filename !== 'string' || !SAFE_FILENAME.test(candidate.filename)) {
    throw new UpdateError('invalid_manifest_asset', 'Ein Update-Asset hat einen ungültigen Dateinamen.');
  }
  if (typeof candidate.sha256 !== 'string' || !/^[0-9a-f]{64}$/.test(candidate.sha256)) {
    throw new UpdateError('invalid_manifest_asset', 'Ein Update-Asset hat keine gültige SHA-256-Prüfsumme.');
  }
  if (!Number.isSafeInteger(candidate.size) || candidate.size <= 0 || candidate.size > MAX_ASSET_BYTES) {
    throw new UpdateError('invalid_manifest_asset', 'Ein Update-Asset hat eine ungültige Größe.');
  }
  if (candidate.installMode !== 'silent' && candidate.installMode !== 'manual') {
    throw new UpdateError('invalid_manifest_asset', 'Ein Update-Asset hat einen unbekannten Installationsmodus.');
  }
  return {
    filename: candidate.filename,
    sha256: candidate.sha256,
    size: candidate.size,
    installMode: candidate.installMode
  };
}

function sanitizeStoredState(value, currentVersion) {
  if (!ALLOWED_STATES.has(value.status)) {
    throw new UpdateError('invalid_update_state', 'Der gespeicherte Update-Status hat einen unbekannten Zustand.');
  }
  const latestVersion = value.latestVersion === null || value.latestVersion === undefined
    ? null
    : parseVersion(value.latestVersion).text;
  const asset = value.asset ? normalizeAsset(value.asset) : null;
  if (['update_available', 'downloading', 'staged', 'installing', 'installer_started', 'manual_required'].includes(value.status)) {
    if (!latestVersion) throw new UpdateError('invalid_update_state', 'Der gespeicherte Update-Status hat keine Version.');
    if (!asset) throw new UpdateError('invalid_update_state', 'Der gespeicherte Update-Status hat kein Asset.');
  }
  if (value.staged && (!asset || !latestVersion)) {
    throw new UpdateError('invalid_update_state', 'Ein vorbereitetes Update hat kein Asset oder keine Version.');
  }
  const notes = typeof value.notes === 'string' && value.notes.length <= MAX_NOTES_CHARS ? value.notes : '';
  const installMode = asset && (asset.installMode === value.installMode) ? asset.installMode : null;
  let lastError = null;
  if (value.lastError && typeof value.lastError === 'object' && !Array.isArray(value.lastError)) {
    lastError = {
      code: typeof value.lastError.code === 'string' ? value.lastError.code.slice(0, 120) : 'unknown_update_error',
      message: typeof value.lastError.message === 'string' ? value.lastError.message.slice(0, 300) : 'Unbekannter Update-Fehler.'
    };
  }
  if (latestVersion && compareVersions(latestVersion, currentVersion) <= 0 && value.status === 'staged') {
    throw new UpdateError('invalid_update_state', 'Ein vorbereitetes Update darf nicht älter oder gleich der aktuellen Version sein.');
  }
  return {
    status: value.status,
    latestVersion,
    notes,
    asset,
    staged: Boolean(value.staged),
    installMode,
    requiresRestart: Boolean(value.requiresRestart),
    lastError,
    updatedAt: typeof value.updatedAt === 'string' ? value.updatedAt : new Date().toISOString()
  };
}

function parseUpdateManifest(manifestBytes, currentVersion) {
  const raw = Buffer.from(manifestBytes);
  if (raw.length > MAX_MANIFEST_BYTES) {
    throw new UpdateError('manifest_too_large', 'Das Update-Manifest ist zu groß.');
  }
  let manifest;
  try {
    manifest = JSON.parse(raw.toString('utf8'));
  } catch (error) {
    throw new UpdateError('invalid_manifest_json', 'Das Update-Manifest ist kein gültiges JSON.');
  }
  if (!manifest || typeof manifest !== 'object' || Array.isArray(manifest)) {
    throw new UpdateError('invalid_manifest', 'Das Update-Manifest hat ein ungültiges Format.');
  }
  if (manifest.format !== 'streamiov-studio-update-v1') {
    throw new UpdateError('unsupported_manifest', 'Das Update-Manifest hat eine unbekannte Version.');
  }
  const version = manifest.version;
  parseVersion(version);
  if (currentVersion && compareVersions(version, currentVersion) <= 0) {
    return { version, notes: '', assets: {} };
  }
  if (typeof manifest.notes !== 'string' || manifest.notes.length > MAX_NOTES_CHARS) {
    throw new UpdateError('invalid_manifest', 'Die Versionshinweise fehlen oder sind zu lang.');
  }
  if (!manifest.assets || typeof manifest.assets !== 'object' || Array.isArray(manifest.assets)) {
    throw new UpdateError('invalid_manifest', 'Das Update-Manifest enthält keine Asset-Liste.');
  }

  const assets = {};
  for (const target of SUPPORTED_TARGETS) {
    const candidate = manifest.assets[target];
    if (!candidate) continue;
    assets[target] = normalizeAsset(candidate);
  }
  if (!Object.keys(assets).length) {
    throw new UpdateError('no_supported_asset', 'Das Update-Manifest enthält kein unterstütztes Installationsziel.');
  }
  return { version, notes: manifest.notes, assets, releasedAt: typeof manifest.releasedAt === 'string' ? manifest.releasedAt : null };
}

function releaseAssetUrl(version, filename) {
  parseVersion(version);
  if (typeof filename !== 'string' || !SAFE_FILENAME.test(filename)) {
    throw new UpdateError('invalid_manifest_asset', 'Der Update-Dateiname ist ungültig.');
  }
  return RELEASE_BASE_URL + 'studio-v' + version + '/' + encodeURIComponent(filename);
}

function releaseTagUrl(version) {
  parseVersion(version);
  return RELEASE_TAG_URL + 'studio-v' + version;
}

async function fetchBytes(fetchImpl, url, options = {}) {
  const maxBytes = options.maxBytes || MAX_MANIFEST_BYTES;
  const response = await fetchImpl(url, {
    headers: { 'X-Streamiov-Client': 'studio-updater' },
    signal: AbortSignal.timeout(options.timeoutMs || 12000)
  });
  if (!response || !response.ok) {
    throw new UpdateError('update_source_unavailable', 'Die Update-Quelle ist nicht erreichbar.', {
      status: response ? response.status : 0
    });
  }
  const declaredLength = Number(response.headers && response.headers.get ? response.headers.get('content-length') : 0);
  if (Number.isFinite(declaredLength) && declaredLength > maxBytes) {
    throw new UpdateError('update_source_too_large', 'Die Update-Datei überschreitet die erlaubte Größe.');
  }
  const bytes = Buffer.from(await response.arrayBuffer());
  if (bytes.length > maxBytes) {
    throw new UpdateError('update_source_too_large', 'Die Update-Datei überschreitet die erlaubte Größe.');
  }
  return bytes;
}

async function consumeBody(response, maxBytes, writeChunk) {
  const declaredLength = Number(response.headers && response.headers.get ? response.headers.get('content-length') : 0);
  if (Number.isFinite(declaredLength) && declaredLength > maxBytes) {
    throw new UpdateError('update_source_too_large', 'Die Update-Datei überschreitet die erlaubte Größe.');
  }
  let total = 0;
  const accept = async (chunk) => {
    const buffer = Buffer.from(chunk);
    total += buffer.length;
    if (total > maxBytes) {
      throw new UpdateError('update_source_too_large', 'Die Update-Datei überschreitet die erlaubte Größe.');
    }
    await writeChunk(buffer);
  };
  if (response.body && typeof response.body.getReader === 'function') {
    const reader = response.body.getReader();
    try {
      for (;;) {
        const result = await reader.read();
        if (result.done) break;
        await accept(result.value);
      }
    } finally {
      reader.releaseLock();
    }
  } else if (typeof response.arrayBuffer === 'function') {
    await accept(await response.arrayBuffer());
  } else {
    throw new UpdateError('update_source_unreadable', 'Die Update-Quelle liefert keinen lesbaren Datenstrom.');
  }
  return total;
}

async function writeJsonAtomic(fs, target, value) {
  await fs.mkdir(nodePath.dirname(target), { recursive: true, mode: 0o700 });
  const temp = target + '.' + crypto.randomUUID() + '.tmp';
  try {
    await fs.writeFile(temp, JSON.stringify(value, null, 2) + '\n', { mode: 0o600 });
    await fs.rename(temp, target);
  } finally {
    await fs.rm(temp, { force: true }).catch(() => {});
  }
}

async function readJson(fs, target) {
  const raw = await fs.readFile(target, 'utf8');
  const value = JSON.parse(raw);
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error('Ungültiger Update-Status');
  }
  return value;
}

async function launchInstaller(spawnImpl, file, args, platform) {
  const child = spawnImpl(file, args, {
    detached: true,
    stdio: 'ignore',
    windowsHide: true
  });
  if (!child || typeof child.once !== 'function') {
    throw new UpdateError('installer_launch_failed', 'Der Installer konnte nicht gestartet werden.');
  }
  await new Promise((resolve, reject) => {
    let settled = false;
    const finish = (error) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      if (error) reject(error);
      else resolve();
    };
    const timer = setTimeout(() => finish(new UpdateError('installer_launch_timeout',
      'Der Installer hat nicht rechtzeitig gestartet.')), 400);
    child.on('error', (error) => finish(new UpdateError('installer_launch_failed',
      'Der Installer konnte nicht gestartet werden: ' + String(error && error.message ? error.message : error))));
    child.once('spawn', () => finish());
    if (child.pid !== undefined && platform !== 'win32' && typeof child.unref === 'function') child.unref();
  });
}

class StreamiovAppUpdater {
  constructor(options = {}) {
    this.currentVersion = options.currentVersion;
    parseVersion(this.currentVersion);
    this.allowUntrustedTestKey = options.allowUntrustedTestKey === true;
    this.publicKeyPem = options.publicKeyPem || UPDATE_PUBLIC_KEY_PEM;
    this.trustedPublicKeyPem = options.trustedPublicKeyPem || UPDATE_PUBLIC_KEY_PEM;
    if (!this.allowUntrustedTestKey && (
      normalizePublicKey(this.publicKeyPem) !== normalizePublicKey(UPDATE_PUBLIC_KEY_PEM) ||
      normalizePublicKey(this.trustedPublicKeyPem) !== normalizePublicKey(UPDATE_PUBLIC_KEY_PEM)
    )) {
      throw new UpdateError('untrusted_update_key', 'Der Update-Schlüssel entspricht nicht dem fest verankerten Schlüssel.');
    }
    this.manifestUrl = options.manifestUrl || UPDATE_MANIFEST_URL;
    this.signatureUrl = options.signatureUrl || UPDATE_MANIFEST_SIGNATURE_URL;
    this.releaseBaseUrl = options.releaseBaseUrl || RELEASE_BASE_URL;
    this.platform = options.platform || process.platform;
    this.arch = options.arch || process.arch;
    this.target = this.platform + '-' + this.arch;
    this.userDataDir = options.userDataDir;
    if (!this.userDataDir) throw new UpdateError('missing_update_directory', 'Kein Update-Verzeichnis konfiguriert.');
    this.fs = options.fs || fsPromises;
    this.path = options.path || nodePath;
    this.fetchImpl = options.fetchImpl || globalThis.fetch;
    this.spawnImpl = options.spawnImpl || spawn;
    this.packaged = options.packaged !== false;
    this.isUpdateAllowed = options.isUpdateAllowed || (() => true);
    this.maxAssetBytes = options.maxAssetBytes || MAX_ASSET_BYTES;
    this.now = options.now || (() => new Date().toISOString());
    this.updateDir = this.path.join(this.userDataDir, 'updates');
    this.stageRoot = this.path.join(this.updateDir, 'staged');
    this.statePath = this.path.join(this.updateDir, 'update-state.json');
    this.previousStatePath = this.path.join(this.updateDir, 'update-state.previous.json');
    this.state = {
      status: 'idle',
      currentVersion: this.currentVersion,
      latestVersion: null,
      notes: '',
      asset: null,
      staged: false,
      installMode: null,
      requiresRestart: false,
      lastError: null,
      updatedAt: this.now()
    };
  }

  status() {
    return {
      ok: true,
      state: this.state.status,
      currentVersion: this.currentVersion,
      latestVersion: this.state.latestVersion,
      notes: this.state.notes,
      asset: this.state.asset,
      staged: Boolean(this.state.staged),
      installMode: this.state.installMode,
      requiresRestart: Boolean(this.state.requiresRestart),
      lastError: this.state.lastError,
      target: this.target,
      supported: SUPPORTED_TARGETS.has(this.target),
      keyFingerprint: publicKeyFingerprint(this.publicKeyPem),
      updateUrl: this.state.latestVersion ? releaseTagUrl(this.state.latestVersion) : null
    };
  }

  async persist() {
    await writeJsonAtomic(this.fs, this.statePath, this.state);
  }

  async setStatus(patch) {
    this.state = { ...this.state, ...patch, updatedAt: this.now() };
    await this.persist();
  }

  async savePreviousState() {
    await writeJsonAtomic(this.fs, this.previousStatePath, {
      ...this.state,
      status: 'idle',
      staged: false,
      requiresRestart: false,
      lastError: null,
      updatedAt: this.now()
    });
  }

  async restorePreviousState(code, message) {
    let previous = null;
    try {
      previous = await readJson(this.fs, this.previousStatePath);
    } catch (error) {
      previous = null;
    }
    let safePrevious = null;
    if (previous) {
      try {
        safePrevious = sanitizeStoredState(previous, this.currentVersion);
      } catch (error) {
        safePrevious = null;
      }
    }
    await this.setStatus({
      status: 'rolled_back',
      currentVersion: this.currentVersion,
      latestVersion: safePrevious ? safePrevious.latestVersion : null,
      notes: safePrevious ? safePrevious.notes : '',
      asset: safePrevious ? safePrevious.asset : null,
      staged: false,
      installMode: null,
      requiresRestart: false,
      lastError: { code, message }
    });
    await this.fs.rm(this.previousStatePath, { force: true }).catch(() => {});
  }

  async cleanupStaged(version) {
    if (!version || !VERSION_PATTERN.test(version)) return;
    await this.fs.rm(this.path.join(this.stageRoot, version), { recursive: true, force: true }).catch(() => {});
  }

  async recover() {
    await this.fs.mkdir(this.stageRoot, { recursive: true, mode: 0o700 });
    let stored = null;
    try {
      stored = await readJson(this.fs, this.statePath);
    } catch (error) {
      await this.setStatus({ status: 'idle' });
      return this.status();
    }
    let sanitized;
    try {
      sanitized = sanitizeStoredState(stored, this.currentVersion);
    } catch (error) {
      await this.fs.rm(this.stageRoot, { recursive: true, force: true }).catch(() => {});
      await this.fs.mkdir(this.stageRoot, { recursive: true, mode: 0o700 });
      await this.setStatus({
        status: 'rolled_back',
        latestVersion: null,
        notes: '',
        asset: null,
        staged: false,
        installMode: null,
        requiresRestart: false,
        lastError: { code: 'invalid_update_state_recovered', message: 'Ein manipulierter Update-Status wurde verworfen.' }
      });
      return this.status();
    }
    this.state = { ...this.state, ...sanitized, currentVersion: this.currentVersion };
    if (this.state.status === 'installer_started') {
      if (compareVersions(this.currentVersion, this.state.latestVersion || this.currentVersion) >= 0) {
        await this.cleanupStaged(this.state.latestVersion);
        await this.setStatus({ status: 'idle', staged: false, requiresRestart: false, asset: null, installMode: null });
      }
      return this.status();
    }
    if (BUSY_STATES.has(this.state.status) || this.state.status === 'staged') {
      await this.cleanupStaged(this.state.latestVersion);
      await this.restorePreviousState('interrupted_update_recovered', 'Ein unterbrochenes Update wurde zurückgesetzt.');
      return this.status();
    }
    await this.persist();
    return this.status();
  }

  assertNotBusy() {
    if (BUSY_STATES.has(this.state.status)) {
      throw new UpdateError('update_busy', 'Eine Update-Operation läuft bereits.');
    }
  }

  stagedTarget() {
    const version = this.state.latestVersion;
    parseVersion(version);
    const asset = normalizeAsset(this.state.asset);
    const stageDir = this.path.join(this.stageRoot, version);
    const target = this.path.join(stageDir, asset.filename);
    const relative = this.path.relative(stageDir, target);
    if (relative !== asset.filename || relative.startsWith('..') || this.path.isAbsolute(relative)) {
      throw new UpdateError('invalid_update_state', 'Der vorbereitete Update-Pfad ist ungültig.');
    }
    return { version, asset, stageDir, target };
  }

  async check() {
    this.assertNotBusy();
    await this.setStatus({ status: 'checking', lastError: null });
    try {
      const manifestBytes = await fetchBytes(this.fetchImpl, this.manifestUrl, { maxBytes: MAX_MANIFEST_BYTES });
      const signatureBytes = await fetchBytes(this.fetchImpl, this.signatureUrl, { maxBytes: MAX_SIGNATURE_BYTES });
      verifyManifestSignature(
        manifestBytes, signatureBytes, this.publicKeyPem, this.trustedPublicKeyPem, this.allowUntrustedTestKey
      );
      const manifest = parseUpdateManifest(manifestBytes, this.currentVersion);
      const newer = compareVersions(manifest.version, this.currentVersion) > 0;
      if (!newer) {
        await this.setStatus({
          status: 'idle',
          latestVersion: manifest.version,
          notes: '',
          asset: null,
          staged: false,
          installMode: null,
          requiresRestart: false,
          lastError: null
        });
        return { ok: true, available: false, currentVersion: this.currentVersion, latestVersion: manifest.version };
      }
      const asset = manifest.assets[this.target] || null;
      if (!asset) {
        await this.setStatus({
          status: 'unsupported',
          latestVersion: manifest.version,
          notes: manifest.notes,
          asset: null,
          staged: false,
          installMode: null,
          lastError: { code: 'asset_unavailable_for_platform', message: 'Für dieses System ist kein passendes Update-Asset vorhanden.' }
        });
        return { ok: true, available: true, supported: false, latestVersion: manifest.version, notes: manifest.notes };
      }
      await this.setStatus({
        status: 'update_available',
        latestVersion: manifest.version,
        notes: manifest.notes,
        asset,
        staged: false,
        installMode: asset.installMode,
        requiresRestart: false,
        lastError: null
      });
      return {
        ok: true,
        available: true,
        supported: true,
        currentVersion: this.currentVersion,
        latestVersion: manifest.version,
        notes: manifest.notes,
        asset,
        releaseUrl: releaseTagUrl(manifest.version)
      };
    } catch (error) {
      const failure = updateFailure(error);
      await this.setStatus({ status: 'error', lastError: failure });
      return { ok: false, available: false, currentVersion: this.currentVersion, error: failure };
    }
  }

  async prepare() {
    this.assertNotBusy();
    let checked = null;
    if (this.state.status !== 'update_available' || !this.state.asset || !this.state.latestVersion) {
      checked = await this.check();
      if (!checked.ok) return { ok: false, error: checked.error };
      if (!checked.available) return { ok: true, prepared: false, reason: 'no_update_available' };
      if (checked.supported === false) return { ok: false, error: this.state.lastError };
    }
    if (!this.isUpdateAllowed()) {
      return {
        ok: false,
        error: { code: 'update_blocked_by_active_stream', message: 'Updates sind während eines laufenden Streams gesperrt.' }
      };
    }
    let staged;
    try {
      staged = this.stagedTarget();
    } catch (error) {
      const failure = updateFailure(error);
      await this.setStatus({ status: 'error', lastError: failure });
      return { ok: false, error: failure };
    }
    const { version, asset, stageDir, target } = staged;
    const part = target + '.part';
    await this.savePreviousState();
    await this.setStatus({ status: 'downloading', staged: false, lastError: null });
    try {
      await this.fs.mkdir(stageDir, { recursive: true, mode: 0o700 });
      const response = await this.fetchImpl(releaseAssetUrl(version, asset.filename), {
        headers: { 'X-Streamiov-Client': 'studio-updater' },
        signal: AbortSignal.timeout(30000)
      });
      if (!response || !response.ok) {
        throw new UpdateError('update_source_unavailable', 'Das Update-Asset ist nicht erreichbar.', {
          status: response ? response.status : 0
        });
      }
      const hash = crypto.createHash('sha256');
      const handle = await this.fs.open(part, 'wx', 0o600);
      let downloaded = 0;
      try {
        downloaded = await consumeBody(response, this.maxAssetBytes, async (chunk) => {
          hash.update(chunk);
          await handle.appendFile(chunk);
        });
      } catch (error) {
        await handle.close().catch(() => {});
        await this.fs.rm(part, { force: true }).catch(() => {});
        throw error;
      }
      await handle.close();
      if (downloaded !== asset.size) {
        await this.fs.rm(part, { force: true });
        throw new UpdateError('size_mismatch', 'Die heruntergeladene Update-Datei hat eine unerwartete Größe.');
      }
      if (hash.digest('hex') !== asset.sha256) {
        await this.fs.rm(part, { force: true });
        throw new UpdateError('sha256_mismatch', 'Die heruntergeladene Update-Datei hat eine falsche Prüfsumme.');
      }
      await this.fs.rename(part, target);
      await this.fs.chmod(target, 0o700);
      await this.setStatus({ status: 'staged', staged: true, installMode: asset.installMode, lastError: null });
      return { ok: true, prepared: true, version, asset: { ...asset }, installMode: asset.installMode };
    } catch (error) {
      const failure = updateFailure(error);
      await this.cleanupStaged(version);
      await this.restorePreviousState(failure.code, failure.message);
      return { ok: false, error: failure };
    }
  }

  async install() {
    this.assertNotBusy();
    if (this.state.status !== 'staged' || !this.state.staged) {
      const prepared = await this.prepare();
      if (!prepared.ok) return { ok: false, error: prepared.error };
      if (!prepared.prepared) return { ok: true, installed: false, reason: prepared.reason };
    }
    if (!this.isUpdateAllowed()) {
      return {
        ok: false,
        error: { code: 'update_blocked_by_active_stream', message: 'Updates sind während eines laufenden Streams gesperrt.' }
      };
    }
    if (!this.packaged) {
      return {
        ok: false,
        error: {
          code: 'install_blocked_unpackaged',
          message: 'Die Installation ist nur in einer gebauten Studio-App erlaubt.',
          releaseUrl: releaseTagUrl(this.state.latestVersion)
        }
      };
    }
    let staged;
    try {
      staged = this.stagedTarget();
    } catch (error) {
      const failure = updateFailure(error);
      await this.setStatus({ status: 'error', lastError: failure });
      return { ok: false, error: failure };
    }
    const { version, asset, target } = staged;
    await this.setStatus({ status: 'installing', lastError: null });
    try {
      const staged = await this.fs.readFile(target);
      const digest = crypto.createHash('sha256').update(staged).digest('hex');
      if (digest !== asset.sha256 || staged.length !== asset.size) {
        throw new UpdateError('staged_asset_invalid', 'Die vorbereitete Update-Datei ist beschädigt.');
      }
      await this.savePreviousState();
      if (asset.installMode === 'manual') {
        const releaseUrl = releaseTagUrl(version);
        await this.setStatus({ status: 'manual_required', staged: true, requiresRestart: false, lastError: null });
        return { ok: true, installed: false, status: 'manual_required', version, releaseUrl };
      }
      if (this.platform !== 'win32' && this.platform !== 'linux') {
        throw new UpdateError('unsupported_platform', 'Für dieses Betriebssystem ist keine automatische Installation verfügbar.');
      }
      const args = this.platform === 'win32' ? ['/S'] : [];
      await launchInstaller(this.spawnImpl, target, args, this.platform);
      await this.setStatus({ status: 'installer_started', staged: true, requiresRestart: true, lastError: null });
      return { ok: true, installed: true, status: 'installer_started', version, restartRequired: true };
    } catch (error) {
      const failure = updateFailure(error);
      await this.cleanupStaged(version);
      await this.restorePreviousState(failure.code, failure.message);
      return { ok: false, error: failure };
    }
  }

  async clearError() {
    if (!['error', 'rolled_back', 'unsupported', 'installer_started'].includes(this.state.status)) return this.status();
    if (this.state.status === 'installer_started') {
      await this.cleanupStaged(this.state.latestVersion);
      await this.fs.rm(this.previousStatePath, { force: true }).catch(() => {});
      await this.setStatus({
        status: 'idle', lastError: null, staged: false, requiresRestart: false,
        latestVersion: null, notes: '', asset: null, installMode: null
      });
      return this.status();
    }
    await this.setStatus({ status: 'idle', lastError: null, staged: false, requiresRestart: false });
    return this.status();
  }
}

module.exports = {
  UPDATE_MANIFEST_URL,
  UPDATE_MANIFEST_SIGNATURE_URL,
  RELEASE_BASE_URL,
  UPDATE_PUBLIC_KEY_PEM,
  MAX_ASSET_BYTES,
  SUPPORTED_TARGETS,
  UpdateError,
  compareVersions,
  parseVersion,
  parseUpdateManifest,
  publicKeyFingerprint,
  releaseAssetUrl,
  releaseTagUrl,
  verifyManifestSignature,
  StreamiovAppUpdater
};
