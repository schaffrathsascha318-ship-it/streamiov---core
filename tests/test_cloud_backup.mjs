import test from "node:test";
import assert from "node:assert/strict";
import { randomBytes } from "node:crypto";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import backupModule from "../core/cloud-backup.js";

const { CloudBackup } = backupModule;

function freshKey() {
  return randomBytes(32).toString("base64");
}

function tempDir(t) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "streamiov-backup-test-"));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  return dir;
}

function readRecord(dir, name) {
  return JSON.parse(fs.readFileSync(path.join(dir, `${name}.bak`), "utf8"));
}

function writeRecord(dir, name, record) {
  fs.writeFileSync(path.join(dir, `${name}.bak`), JSON.stringify(record));
}

test("create and restore round-trip with file metadata and 0600 permissions", (t) => {
  const baseDir = path.join(tempDir(t), "nested");
  const backup = new CloudBackup({ baseDir });
  assert.equal(fs.existsSync(baseDir), false);

  const key = freshKey();
  const data = { account: "demo@example.invalid", settings: { theme: "dark" }, list: [1, true, null] };
  const meta = backup.create("round-trip", data, { key });

  assert.equal(fs.existsSync(baseDir), true);
  assert.equal(meta.name, "round-trip");
  assert.equal(meta.version, 1);
  assert.equal(meta.byteLength, Buffer.byteLength(JSON.stringify(data), "utf8"));
  assert.match(meta.sha256, /^[0-9a-f]{64}$/);
  assert.deepEqual(backup.restore("round-trip", { key }), data);
  assert.equal(fs.statSync(path.join(baseDir, "round-trip.bak")).mode & 0o777, 0o600);

  assert.equal(backup.verify("round-trip").decryption, "not_checked");
  assert.equal(backup.verify("round-trip").structure, "ok");
  assert.equal(backup.verify("round-trip", { key }).decryption, "ok");
});

test("create and restore refuse missing keys and reject wrong keys", (t) => {
  const dir = tempDir(t);
  const backup = new CloudBackup({ baseDir: dir });
  const key = freshKey();
  const wrongKey = freshKey();
  backup.create("wrong-key", { value: 42 }, { key });

  assert.throws(() => backup.create("no-key", { value: 1 }), /key required/i);
  assert.throws(() => backup.restore("wrong-key"), /key required/i);
  assert.throws(() => backup.restore("wrong-key", { key: wrongKey }), /wrong key or modified/i);
  assert.throws(() => backup.verify("wrong-key", { key: wrongKey }), /wrong key or modified/i);
});

test("tampered ciphertext is rejected", (t) => {
  const dir = tempDir(t);
  const backup = new CloudBackup({ baseDir: dir });
  const key = freshKey();
  backup.create("tamper", { secret: "value" }, { key });

  const record = readRecord(dir, "tamper");
  const index = Math.min(4, record.ciphertext.length - 1);
  const replacement = record.ciphertext[index] === "A" ? "B" : "A";
  record.ciphertext = record.ciphertext.slice(0, index) + replacement + record.ciphertext.slice(index + 1);
  writeRecord(dir, "tamper", record);

  assert.throws(() => backup.restore("tamper", { key }), /wrong key or modified/i);
  assert.throws(() => backup.verify("tamper", { key }), /wrong key or modified/i);
});

test("unsafe backup names are rejected before any file is written", (t) => {
  const dir = tempDir(t);
  const backup = new CloudBackup({ baseDir: dir });
  const key = freshKey();
  const unsafe = ["../escape", "a/b", "..", ".", "", "bad.name", "has space", ".hidden"];

  for (const name of unsafe) {
    assert.throws(() => backup.create(name, { x: 1 }, { key }), /invalid backup name/i, name);
    assert.throws(() => backup.restore(name, { key }), /invalid backup name/i, name);
    assert.throws(() => backup.delete(name), /invalid backup name/i, name);
  }
  assert.equal(fs.existsSync(path.join(path.dirname(dir), "escape.bak")), false);
  assert.deepEqual(backup.list(), []);
});

test("list returns sorted backup ids and ignores temporary files", (t) => {
  const dir = tempDir(t);
  const backup = new CloudBackup({ baseDir: dir });
  const key = freshKey();
  backup.create("beta", { b: 2 }, { key });
  backup.create("alpha", { a: 1 }, { key });
  fs.writeFileSync(path.join(dir, "stray.deadbeef.tmp"), "not a backup");

  assert.deepEqual(backup.list(), ["alpha", "beta"]);
  assert.equal(backup.delete("alpha"), true);
  assert.equal(backup.delete("alpha"), false);
  assert.deepEqual(backup.list(), ["beta"]);
});

test("backup file contains neither plaintext nor key", (t) => {
  const dir = tempDir(t);
  const backup = new CloudBackup({ baseDir: dir });
  const key = freshKey();
  const marker = `SECRET_MARKER_${randomBytes(16).toString("hex")}`;
  const data = { token: marker, nested: [marker] };
  backup.create("sealed", data, { key });

  const raw = fs.readFileSync(path.join(dir, "sealed.bak"), "utf8");
  assert.ok(!raw.includes(marker));
  assert.ok(!raw.includes(key));
  assert.ok(!raw.includes(Buffer.from(key, "base64").toString("utf8")));
  assert.match(raw, /"version":1/);
  assert.match(raw, /"createdAt":"/);
  assert.match(raw, /"byteLength":\d+/);
  assert.match(raw, /"sha256":"[0-9a-f]{64}"/);
  assert.deepEqual(backup.restore("sealed", { key }), data);
});

test("key may be supplied through STREAMIOV_BACKUP_KEY", (t) => {
  const dir = tempDir(t);
  const backup = new CloudBackup({ baseDir: dir });
  const key = freshKey();
  const previous = process.env.STREAMIOV_BACKUP_KEY;
  process.env.STREAMIOV_BACKUP_KEY = key;
  t.after(() => {
    if (previous === undefined) delete process.env.STREAMIOV_BACKUP_KEY;
    else process.env.STREAMIOV_BACKUP_KEY = previous;
  });

  const data = { source: "environment" };
  backup.create("env-key", data);
  assert.deepEqual(backup.restore("env-key"), data);
});
