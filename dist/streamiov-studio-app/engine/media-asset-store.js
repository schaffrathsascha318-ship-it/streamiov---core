'use strict';

const { randomUUID } = require('node:crypto');
const fs = require('node:fs/promises');
const path = require('node:path');

const STORE_VERSION = 1;
const MAX_FILE_SIZE = 100 * 1024 * 1024;
const MAX_ASSETS = 128;
const MEDIA_EXTENSIONS = Object.freeze({
  image: Object.freeze(['.png', '.jpg', '.jpeg', '.gif', '.webp']),
  video: Object.freeze(['.webm', '.mp4', '.ogg', '.mov']),
  audio: Object.freeze(['.wav', '.mp3', '.ogg', '.m4a', '.flac'])
});

const validId = value => typeof value === 'string' && /^[a-f0-9-]{36}$/.test(value);

function inferKind(filePath) {
  const extension = path.extname(filePath).toLowerCase();
  for (const [kind, extensions] of Object.entries(MEDIA_EXTENSIONS)) {
    if (extensions.includes(extension)) return kind;
  }
  return null;
}

function cleanAsset(raw) {
  if (!raw || typeof raw !== 'object') return null;
  if (!validId(raw.id) || !Object.hasOwn(MEDIA_EXTENSIONS, raw.kind)) return null;
  if (typeof raw.fileName !== 'string' || !/^[a-zA-Z0-9._-]{1,120}$/.test(raw.fileName)) return null;
  if (!Number.isInteger(raw.size) || raw.size < 0) return null;
  return {
    id: raw.id,
    kind: raw.kind,
    name: typeof raw.name === 'string' ? raw.name.slice(0, 120) : raw.fileName,
    fileName: raw.fileName,
    size: raw.size,
    createdAt: typeof raw.createdAt === 'string' ? raw.createdAt : new Date(0).toISOString()
  };
}

function createMediaAssetStore({ rootDir, now = () => new Date().toISOString() }) {
  if (typeof rootDir !== 'string' || !rootDir) throw new TypeError('A media root directory is required.');
  const manifestPath = path.join(rootDir, 'media-assets.json');
  let assets = [];

  async function save() {
    await fs.mkdir(rootDir, { recursive: true, mode: 0o700 });
    const temporary = manifestPath + '.' + randomUUID() + '.tmp';
    await fs.writeFile(temporary, JSON.stringify({ version: STORE_VERSION, assets }, null, 2), { mode: 0o600 });
    await fs.rename(temporary, manifestPath);
  }

  return {
    async load() {
      let saved = {};
      try {
        saved = JSON.parse(await fs.readFile(manifestPath, 'utf8'));
      } catch (error) {
        if (error.code !== 'ENOENT') throw error;
      }
      const seen = new Set();
      assets = (Array.isArray(saved.assets) ? saved.assets : [])
        .map(cleanAsset)
        .filter(asset => {
          if (!asset || seen.has(asset.id)) return false;
          seen.add(asset.id);
          return true;
        })
        .slice(0, MAX_ASSETS);
      return this.list();
    },
    list() {
      return assets.map(asset => ({ ...asset }));
    },
    resolve(id) {
      if (!validId(id)) return null;
      const asset = assets.find(item => item.id === id);
      if (!asset) return null;
      return path.join(rootDir, asset.fileName);
    },
    async importFile(filePath, requestedKind) {
      if (assets.length >= MAX_ASSETS) throw new Error(`Maximal ${MAX_ASSETS} Mediendateien sind möglich.`);
      if (typeof filePath !== 'string' || !filePath) throw new TypeError('Eine Mediendatei ist erforderlich.');
      const kind = requestedKind && Object.hasOwn(MEDIA_EXTENSIONS, requestedKind)
        ? requestedKind
        : inferKind(filePath);
      if (!kind) throw new Error('Dateityp wird nicht unterstützt.');
      const extension = path.extname(filePath).toLowerCase();
      if (!MEDIA_EXTENSIONS[kind].includes(extension)) throw new Error('Dateityp passt nicht zur Medienkategorie.');
      const stat = await fs.stat(filePath);
      if (!stat.isFile() || stat.size < 1 || stat.size > MAX_FILE_SIZE) {
        throw new Error('Mediendatei ist leer oder überschreitet 100 MB.');
      }
      const id = randomUUID();
      const fileName = id + extension;
      await fs.mkdir(rootDir, { recursive: true, mode: 0o700 });
      const destination = path.join(rootDir, fileName);
      await fs.copyFile(filePath, destination);
      await fs.chmod(destination, 0o600);
      const asset = {
        id,
        kind,
        name: path.basename(filePath).slice(0, 120),
        fileName,
        size: stat.size,
        createdAt: now()
      };
      assets.push(asset);
      await save();
      return { ...asset };
    },
    async remove(id) {
      const index = assets.findIndex(asset => asset.id === id);
      if (index < 0) return false;
      const [asset] = assets.splice(index, 1);
      await save();
      await fs.unlink(path.join(rootDir, asset.fileName)).catch(() => {});
      return true;
    }
  };
}

module.exports = { MEDIA_EXTENSIONS, MAX_ASSETS, createMediaAssetStore };
