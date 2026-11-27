#!/usr/bin/env node
import { createRequire } from 'node:module';
import { createHash, createPrivateKey, createPublicKey, sign, verify } from 'node:crypto';
import { readFile, mkdir, writeFile } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const require = createRequire(import.meta.url);
const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(scriptDir, '..');
const {
  UPDATE_PUBLIC_KEY_PEM,
  parseVersion,
  parseUpdateManifest,
  verifyManifestSignature
} = require('../dist/streamiov-studio-app/engine/app-updater.js');

function normalizeKey(value) {
  return String(value || '').trim().split(/\r?\n/).map((line) => line.trim()).join('\n');
}

function parseArguments(argv) {
  const options = {
    releaseDir: null,
    version: null,
    privateKey: path.join(os.homedir(), '.config', 'streamiov', 'release-signing.key'),
    publicKey: path.join(repoRoot, 'dist/streamiov-homepage-worker/public/downloads/STREAMIOV-RELEASE-KEY.pub'),
    outDir: null,
    notes: 'Signiertes Studio-Updatepaket.',
    notesFile: null,
    releasedAt: new Date().toISOString()
  };
  for (let index = 0; index < argv.length; index += 1) {
    const flag = argv[index];
    const take = () => {
      const value = argv[index + 1];
      if (!value || value.startsWith('--')) throw new Error('Fehlender Wert für ' + flag);
      index += 1;
      return value;
    };
    if (flag === '--release-dir') options.releaseDir = take();
    else if (flag === '--version') options.version = take();
    else if (flag === '--private-key') options.privateKey = take();
    else if (flag === '--public-key') options.publicKey = take();
    else if (flag === '--out-dir') options.outDir = take();
    else if (flag === '--notes') options.notes = take();
    else if (flag === '--notes-file') options.notesFile = take();
    else if (flag === '--released-at') options.releasedAt = take();
    else if (flag === '--help' || flag === '-h') {
      console.log('Verwendung: build-studio-update-manifest.mjs --release-dir <ordner> --version <x.y.z> [--private-key <datei>] [--public-key <datei>] --out-dir <ordner> [--notes <text>] [--notes-file <datei>] [--released-at <iso>]');
      process.exit(0);
    } else throw new Error('Unbekannte Option: ' + flag);
  }
  if (!options.releaseDir || !options.version || !options.outDir) {
    throw new Error('--release-dir, --version und --out-dir sind erforderlich.');
  }
  parseVersion(options.version);
  if (Number.isNaN(Date.parse(options.releasedAt))) throw new Error('--released-at ist kein gültiges Datum.');
  if (options.notesFile) options.notes = null;
  return options;
}

function candidatesFor(version) {
  return [
    {
      target: 'win32-x64',
      entries: [
        { filename: 'Streamiov.Studio.Setup.' + version + '-x64.exe', installMode: 'silent' }
      ]
    },
    {
      target: 'win32-arm64',
      entries: [
        { filename: 'Streamiov.Studio.Setup.' + version + '-arm64.exe', installMode: 'silent' }
      ]
    },
    {
      target: 'linux-x64',
      entries: [
        { filename: 'Streamiov.Studio-' + version + '-x64.AppImage', installMode: 'silent' },
        { filename: 'streamiov-studio_' + version + '_amd64.deb', installMode: 'manual' }
      ]
    },
    {
      target: 'linux-arm64',
      entries: [
        { filename: 'Streamiov.Studio-' + version + '-arm64.AppImage', installMode: 'silent' },
        { filename: 'streamiov-studio_' + version + '_arm64.deb', installMode: 'manual' }
      ]
    }
  ];
}

async function main() {
  const options = parseArguments(process.argv.slice(2));
  const publicPem = await readFile(options.publicKey, 'utf8');
  if (normalizeKey(publicPem) !== normalizeKey(UPDATE_PUBLIC_KEY_PEM)) {
    throw new Error('Der angegebene Public Key entspricht nicht dem in der App verankerten Update-Schlüssel.');
  }
  const publicKey = createPublicKey(normalizeKey(publicPem));
  const privateKey = createPrivateKey(await readFile(options.privateKey, 'utf8'));
  if (privateKey.asymmetricKeyType !== 'ed25519') {
    throw new Error('Der Private Key ist kein Ed25519-Schlüssel.');
  }
  const probe = Buffer.from('streamiov-update-key-check');
  if (!verify(null, probe, publicKey, sign(null, probe, privateKey))) {
    throw new Error('Private Key und Public Key passen nicht zusammen.');
  }

  const notes = options.notes === null
    ? await readFile(options.notesFile, 'utf8')
    : options.notes;
  if (typeof notes !== 'string' || notes.length > 5000) {
    throw new Error('Die Versionshinweise fehlen oder sind zu lang.');
  }

  const assets = {};
  for (const candidate of candidatesFor(options.version)) {
    for (const entry of candidate.entries) {
      const file = path.join(options.releaseDir, entry.filename);
      let bytes;
      try {
        bytes = await readFile(file);
      } catch (error) {
        if (error && error.code === 'ENOENT') continue;
        throw error;
      }
      assets[candidate.target] = {
        filename: entry.filename,
        sha256: createHash('sha256').update(bytes).digest('hex'),
        size: bytes.length,
        installMode: entry.installMode
      };
      break;
    }
  }
  if (!Object.keys(assets).length) {
    throw new Error('Im Release-Verzeichnis wurde kein unterstütztes Studio-Asset gefunden.');
  }

  const manifest = {
    format: 'streamiov-studio-update-v1',
    version: options.version,
    releasedAt: options.releasedAt,
    notes,
    assets
  };
  const bytes = Buffer.from(JSON.stringify(manifest, null, 2) + '\n', 'utf8');
  parseUpdateManifest(bytes, '0.0.0');
  const signature = sign(null, bytes, privateKey).toString('base64') + '\n';
  verifyManifestSignature(bytes, Buffer.from(signature), publicPem);
  await mkdir(options.outDir, { recursive: true });
  await writeFile(path.join(options.outDir, 'studio-update.json'), bytes);
  await writeFile(path.join(options.outDir, 'studio-update.json.sig'), signature, 'ascii');
  console.log('Update-Manifest erstellt: ' + options.version + ' · ' + Object.keys(assets).join(', '));
}

main().catch((error) => {
  console.error('Update-Manifest konnte nicht erstellt werden: ' + String(error && error.message ? error.message : error));
  process.exitCode = 1;
});
