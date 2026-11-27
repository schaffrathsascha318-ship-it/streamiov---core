"use strict";

const crypto = require("node:crypto");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const FORMAT_VERSION = 1;
const ALGORITHM = "aes-256-gcm";
const IV_BYTES = 12;
const TAG_BYTES = 16;
const KEY_BYTES = 32;
const MAX_PAYLOAD_BYTES = 16 * 1024 * 1024;
const MAX_FILE_BYTES = MAX_PAYLOAD_BYTES * 2 + 4096;
const NAME_RE = /^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$/;
const FILE_RE = /^([A-Za-z0-9][A-Za-z0-9_-]{0,127})\.bak$/;
const BASE64_RE = /^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/;
const HEX_SHA256_RE = /^[0-9a-f]{64}$/;

function fail(code, message) {
  const error = new Error(message);
  error.code = code;
  return error;
}

function validateName(name) {
  if (typeof name !== "string" || !NAME_RE.test(name)) {
    throw fail("BACKUP_NAME_INVALID", "Invalid backup name: use 1-128 letters, digits, underscores or hyphens, starting with a letter or digit.");
  }
  return name;
}

function decodeBase64(value, field, code = "BACKUP_ENCODING_INVALID", message) {
  if (typeof value !== "string" || !BASE64_RE.test(value)) {
    throw fail(code, message || `Invalid base64 in ${field}.`);
  }
  const bytes = Buffer.from(value, "base64");
  if (bytes.toString("base64") !== value) {
    throw fail(code, message || `Invalid base64 in ${field}.`);
  }
  return bytes;
}

function normalizeKey(value) {
  const message = "Backup key must be base64-encoded and exactly 32 bytes.";
  let key;
  if (Buffer.isBuffer(value)) {
    key = value;
  } else if (typeof value === "string") {
    key = decodeBase64(value, "backup key", "BACKUP_KEY_INVALID", message);
  } else {
    throw fail("BACKUP_KEY_INVALID", message);
  }
  if (key.length !== KEY_BYTES) throw fail("BACKUP_KEY_INVALID", message);
  return key;
}

function resolveKey(options, required) {
  const opts = options && typeof options === "object" ? options : {};
  let raw;
  if (Object.prototype.hasOwnProperty.call(opts, "key")) {
    raw = opts.key;
  } else {
    const env = opts.env && typeof opts.env === "object" ? opts.env : process.env;
    raw = env.STREAMIOV_BACKUP_KEY;
  }
  if (raw === undefined || raw === null || raw === "") {
    if (required) {
      throw fail("BACKUP_KEY_REQUIRED", "Backup key required: pass options.key or set STREAMIOV_BACKUP_KEY (base64, 32 bytes).");
    }
    return null;
  }
  return normalizeKey(raw);
}

function aadFor(fields) {
  return Buffer.from(`streamiov-backup:v${fields.version}:${fields.name}:${fields.createdAt}:${fields.byteLength}:${fields.sha256}`, "utf8");
}

function serialize(data) {
  let json;
  try {
    json = JSON.stringify(data);
  } catch (_) {
    throw fail("BACKUP_DATA_INVALID", "Backup data must be JSON-serializable.");
  }
  if (typeof json !== "string") throw fail("BACKUP_DATA_INVALID", "Backup data must be JSON-serializable.");
  const plaintext = Buffer.from(json, "utf8");
  if (plaintext.length > MAX_PAYLOAD_BYTES) {
    throw fail("BACKUP_TOO_LARGE", `Backup payload exceeds the ${MAX_PAYLOAD_BYTES}-byte limit.`);
  }
  return plaintext;
}

function hashPlaintext(plaintext) {
  return crypto.createHash("sha256").update(plaintext).digest("hex");
}

function parseEnvelope(bytes, name) {
  let record;
  try {
    record = JSON.parse(bytes.toString("utf8"));
  } catch (_) {
    throw fail("BACKUP_FORMAT_INVALID", "Backup file is not valid JSON.");
  }
  const valid = record !== null && typeof record === "object" && !Array.isArray(record)
    && record.version === FORMAT_VERSION
    && record.algorithm === ALGORITHM
    && record.name === name
    && typeof record.createdAt === "string"
    && new Date(record.createdAt).toISOString() === record.createdAt
    && Number.isSafeInteger(record.byteLength)
    && record.byteLength >= 0
    && record.byteLength <= MAX_PAYLOAD_BYTES
    && typeof record.sha256 === "string"
    && HEX_SHA256_RE.test(record.sha256)
    && typeof record.iv === "string"
    && typeof record.tag === "string"
    && typeof record.ciphertext === "string";
  if (!valid) throw fail("BACKUP_FORMAT_INVALID", "Backup metadata is invalid or unsupported.");

  const iv = decodeBase64(record.iv, "iv");
  const tag = decodeBase64(record.tag, "tag");
  const ciphertext = decodeBase64(record.ciphertext, "ciphertext");
  if (iv.length !== IV_BYTES || tag.length !== TAG_BYTES || ciphertext.length !== record.byteLength) {
    throw fail("BACKUP_FORMAT_INVALID", "Backup metadata does not match the encrypted payload.");
  }
  return {
    version: record.version,
    algorithm: record.algorithm,
    name: record.name,
    createdAt: record.createdAt,
    byteLength: record.byteLength,
    sha256: record.sha256,
    iv,
    tag,
    ciphertext,
  };
}

function decryptEnvelope(envelope, key) {
  const decipher = crypto.createDecipheriv(ALGORITHM, key, envelope.iv);
  decipher.setAAD(aadFor(envelope));
  decipher.setAuthTag(envelope.tag);
  let plaintext;
  try {
    plaintext = Buffer.concat([decipher.update(envelope.ciphertext), decipher.final()]);
  } catch (_) {
    throw fail("BACKUP_AUTHENTICATION_FAILED", "Backup authentication failed: wrong key or modified backup.");
  }
  if (plaintext.length !== envelope.byteLength) {
    throw fail("BACKUP_FORMAT_INVALID", "Backup plaintext length does not match metadata.");
  }
  const actual = Buffer.from(hashPlaintext(plaintext), "utf8");
  const expected = Buffer.from(envelope.sha256, "utf8");
  if (actual.length !== expected.length || !crypto.timingSafeEqual(actual, expected)) {
    throw fail("BACKUP_HASH_MISMATCH", "Backup plaintext hash does not match metadata.");
  }
  return plaintext;
}

function metadata(envelope) {
  return {
    version: envelope.version,
    algorithm: envelope.algorithm,
    name: envelope.name,
    createdAt: envelope.createdAt,
    byteLength: envelope.byteLength,
    sha256: envelope.sha256,
  };
}

function writeAtomic(filePath, bytes) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true, mode: 0o700 });
  const temp = `${filePath}.${crypto.randomBytes(8).toString("hex")}.tmp`;
  try {
    fs.writeFileSync(temp, bytes, { flag: "wx", mode: 0o600 });
    fs.chmodSync(temp, 0o600);
    fs.renameSync(temp, filePath);
  } catch (error) {
    try { fs.unlinkSync(temp); } catch (_) {}
    throw error;
  }
}

class CloudBackup {
  constructor(options = {}) {
    if (options === null || typeof options !== "object") {
      throw fail("BACKUP_OPTIONS_INVALID", "Backup options must be an object.");
    }
    const baseDir = options.baseDir === undefined
      ? path.join(os.homedir(), ".streamiov", "cloud-backups")
      : options.baseDir;
    if (typeof baseDir !== "string" || !baseDir.trim()) {
      throw fail("BACKUP_OPTIONS_INVALID", "Backup baseDir must be a non-empty string.");
    }
    this.baseDir = path.resolve(baseDir);
  }

  create(name, data, options) {
    const id = validateName(name);
    const key = resolveKey(options, true);
    const plaintext = serialize(data);
    const createdAt = new Date().toISOString();
    const sha256 = hashPlaintext(plaintext);
    const fields = { version: FORMAT_VERSION, algorithm: ALGORITHM, name: id, createdAt, byteLength: plaintext.length, sha256 };
    const iv = crypto.randomBytes(IV_BYTES);
    const cipher = crypto.createCipheriv(ALGORITHM, key, iv);
    cipher.setAAD(aadFor(fields));
    const ciphertext = Buffer.concat([cipher.update(plaintext), cipher.final()]);
    const record = {
      ...metadata(fields),
      iv: iv.toString("base64"),
      tag: cipher.getAuthTag().toString("base64"),
      ciphertext: ciphertext.toString("base64"),
    };
    writeAtomic(this._filePath(id), Buffer.from(JSON.stringify(record), "utf8"));
    return metadata(fields);
  }

  list() {
    let entries;
    try {
      entries = fs.readdirSync(this.baseDir, { withFileTypes: true });
    } catch (error) {
      if (error.code === "ENOENT") return [];
      throw error;
    }
    return entries
      .filter((entry) => entry.isFile() && FILE_RE.test(entry.name))
      .map((entry) => entry.name.slice(0, -4))
      .sort();
  }

  verify(name, options) {
    const id = validateName(name);
    const key = resolveKey(options, false);
    const envelope = parseEnvelope(this._read(id), id);
    if (key) decryptEnvelope(envelope, key);
    return { ...metadata(envelope), structure: "ok", decryption: key ? "ok" : "not_checked" };
  }

  restore(name, options) {
    const id = validateName(name);
    const key = resolveKey(options, true);
    const plaintext = decryptEnvelope(parseEnvelope(this._read(id), id), key);
    try {
      return JSON.parse(plaintext.toString("utf8"));
    } catch (_) {
      throw fail("BACKUP_FORMAT_INVALID", "Backup plaintext is not valid JSON.");
    }
  }

  delete(name) {
    const id = validateName(name);
    try {
      fs.unlinkSync(this._filePath(id));
      return true;
    } catch (error) {
      if (error.code === "ENOENT") return false;
      throw error;
    }
  }

  _filePath(id) {
    return path.join(this.baseDir, `${id}.bak`);
  }

  _read(id) {
    let bytes;
    try {
      bytes = fs.readFileSync(this._filePath(id));
    } catch (error) {
      if (error.code === "ENOENT") throw fail("BACKUP_NOT_FOUND", `Backup "${id}" not found.`);
      throw error;
    }
    if (bytes.length > MAX_FILE_BYTES) {
      throw fail("BACKUP_TOO_LARGE", "Backup file exceeds the supported size.");
    }
    return bytes;
  }
}

CloudBackup.MAX_PAYLOAD_BYTES = MAX_PAYLOAD_BYTES;

const singleton = new CloudBackup();
module.exports = singleton;
module.exports.CloudBackup = CloudBackup;
module.exports.default = singleton;
