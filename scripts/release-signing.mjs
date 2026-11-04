#!/usr/bin/env node
/**
 * Free, self-managed release signatures for STREAMIOV.
 *
 * This is NOT Authenticode/Apple code signing and does not make Windows
 * SmartScreen or macOS Gatekeeper trust an installer. It lets anyone verify
 * that the published checksum manifests and source-snapshot parts really came
 * from the STREAMIOV release key, without buying a certificate or a service.
 *
 * The private key stays outside the repository (default:
 * ~/.config/streamiov/release-signing.key). Only the public key and the
 * `.sig` files are published.
 *
 * Usage:
 *   node scripts/release-signing.mjs keygen [--key PATH] [--pub PATH]
 *   node scripts/release-signing.mjs sign <file...> [--key PATH]
 *   node scripts/release-signing.mjs verify <file...> [--pub PATH]
 *   node scripts/release-signing.mjs sign-release [--key PATH] [--pub PATH]
 *   node scripts/release-signing.mjs verify-release [--pub PATH]
 *   node scripts/release-signing.mjs fingerprint [--pub PATH]
 */
import crypto from "node:crypto";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const DOWNLOADS = path.join(ROOT, "dist/streamiov-homepage-worker/public/downloads");
const DEFAULT_KEY = path.join(os.homedir(), ".config/streamiov/release-signing.key");
const DEFAULT_PUB = path.join(DOWNLOADS, "STREAMIOV-RELEASE-KEY.pub");
const MANIFESTS = ["SHA256SUMS.txt", "SHA256SUMS-games.txt"];

function fail(message) {
  console.error(`FEHLER: ${message}`);
  process.exit(1);
}

function parseArgs(argv) {
  const args = { _: [] };
  for (let index = 0; index < argv.length; index += 1) {
    const item = argv[index];
    if (item === "--key" || item === "--pub" || item === "--dir") {
      const value = argv[index + 1];
      if (!value) fail(`${item} benötigt einen Pfad`);
      args[item.slice(2)] = value;
      index += 1;
    } else if (item === "--help" || item === "-h") {
      args.help = true;
    } else {
      args._.push(item);
    }
  }
  return args;
}

function insideRepo(target) {
  const relative = path.relative(ROOT, path.resolve(target));
  return relative === "" || (!relative.startsWith("..") && !path.isAbsolute(relative));
}

function readKey(privateKeyPath) {
  if (!fs.existsSync(privateKeyPath)) {
    fail(`Privater Schlüssel fehlt: ${privateKeyPath}\nErzeuge ihn einmalig mit: node scripts/release-signing.mjs keygen`);
  }
  const pem = fs.readFileSync(privateKeyPath, "utf8");
  try {
    return crypto.createPrivateKey(pem);
  } catch {
    fail(`Privater Schlüssel ist keine gültige PEM-Datei: ${privateKeyPath}`);
  }
}

function readPublicKey(publicKeyPath) {
  if (!fs.existsSync(publicKeyPath)) fail(`Öffentlicher Schlüssel fehlt: ${publicKeyPath}`);
  try {
    return crypto.createPublicKey(fs.readFileSync(publicKeyPath, "utf8"));
  } catch {
    fail(`Öffentlicher Schlüssel ist keine gültige PEM-Datei: ${publicKeyPath}`);
  }
}

function fingerprint(publicKey) {
  const der = publicKey.export({ type: "spki", format: "der" });
  return crypto.createHash("sha256").update(der).digest("hex");
}

function signaturePath(file) {
  return `${file}.sig`;
}

function signFile(file, privateKey) {
  const payload = fs.readFileSync(file);
  const signature = crypto.sign(null, payload, privateKey).toString("base64");
  fs.writeFileSync(signaturePath(file), `${signature}\n`, { mode: 0o644 });
  return signaturePath(file);
}

function verifyFile(file, publicKey) {
  const sigPath = signaturePath(file);
  if (!fs.existsSync(sigPath)) return { file, ok: false, error: "Signatur fehlt" };
  const signature = Buffer.from(fs.readFileSync(sigPath, "utf8").trim(), "base64");
  const ok = crypto.verify(null, fs.readFileSync(file), publicKey, signature);
  return { file, ok, error: ok ? undefined : "Signatur passt nicht zum Inhalt" };
}

function keygen(args) {
  const keyPath = path.resolve(args.key || DEFAULT_KEY);
  const pubPath = path.resolve(args.pub || DEFAULT_PUB);
  if (insideRepo(keyPath)) {
    fail(`Der private Schlüssel darf nicht im Repository liegen: ${keyPath}`);
  }
  if (fs.existsSync(keyPath)) {
    fail(`Privater Schlüssel existiert bereits und wird nicht überschrieben: ${keyPath}`);
  }
  fs.mkdirSync(path.dirname(keyPath), { recursive: true, mode: 0o700 });
  const { publicKey, privateKey } = crypto.generateKeyPairSync("ed25519");
  fs.writeFileSync(keyPath, privateKey.export({ type: "pkcs8", format: "pem" }), { mode: 0o600 });
  fs.writeFileSync(pubPath, publicKey.export({ type: "spki", format: "pem" }), { mode: 0o644 });
  console.log(JSON.stringify({
    ok: true,
    privateKey: keyPath,
    publicKey: pubPath,
    fingerprint: fingerprint(publicKey),
    note: "Privaten Schlüssel sichern. Er gehört nicht ins Repository und darf nicht veröffentlicht werden.",
  }, null, 2));
}

function signRelease(args) {
  const privateKey = readKey(path.resolve(args.key || DEFAULT_KEY));
  const publicKey = crypto.createPublicKey(privateKey);
  const downloads = path.resolve(args.dir || DOWNLOADS);
  const pubPath = path.resolve(args.pub || DEFAULT_PUB);
  fs.mkdirSync(path.dirname(pubPath), { recursive: true });
  fs.writeFileSync(pubPath, publicKey.export({ type: "spki", format: "pem" }), { mode: 0o644 });
  const signed = [];
  for (const name of MANIFESTS) {
    const file = path.join(downloads, name);
    if (fs.existsSync(file)) signed.push({ file: name, signature: path.basename(signFile(file, privateKey)) });
  }
  console.log(JSON.stringify({
    ok: true,
    publicKey: pubPath,
    fingerprint: fingerprint(publicKey),
    signed,
  }, null, 2));
}

function verifyRelease(args) {
  const publicKey = readPublicKey(path.resolve(args.pub || DEFAULT_PUB));
  const downloads = path.resolve(args.dir || DOWNLOADS);
  const checks = [];
  let ok = true;
  for (const name of MANIFESTS) {
    const file = path.join(downloads, name);
    if (!fs.existsSync(file)) continue;
    const result = verifyFile(file, publicKey);
    checks.push({ check: `signature:${name}`, ok: result.ok, error: result.error });
    ok = ok && result.ok;
  }

  const sumsPath = path.join(downloads, "SHA256SUMS.txt");
  const parts = [];
  if (!fs.existsSync(sumsPath)) {
    checks.push({ check: "manifest:SHA256SUMS.txt", ok: false, error: `fehlt in ${downloads}` });
    ok = false;
  } else {
    for (const line of fs.readFileSync(sumsPath, "utf8").split(/\r?\n/)) {
      if (!line || line.startsWith("#")) continue;
      const match = /^([0-9a-f]{64})  ([^/\\]+)$/.exec(line);
      if (!match) {
        checks.push({ check: `manifest:${line}`, ok: false, error: "ungültige Zeile" });
        ok = false;
        continue;
      }
      const [, expected, name] = match;
      const target = path.join(downloads, name);
      const exists = fs.existsSync(target);
      const actual = exists ? crypto.createHash("sha256").update(fs.readFileSync(target)).digest("hex") : null;
      const matches = actual === expected;
      checks.push({ check: `sha256:${name}`, ok: exists && matches, error: !exists ? "Datei fehlt" : matches ? undefined : "Prüfsumme falsch" });
      ok = ok && exists && matches;
      if (/^streamiov-studio-part-\d{2}\.bin$/.test(name)) parts.push(target);
    }
    const expectedArchive = /^# assembled archive: ([0-9a-f]{64})/m.exec(fs.readFileSync(sumsPath, "utf8"));
    if (expectedArchive) {
      parts.sort();
      const assembled = crypto.createHash("sha256");
      for (const part of parts) assembled.update(fs.readFileSync(part));
      const digest = assembled.digest("hex");
      const matches = digest === expectedArchive[1];
      checks.push({ check: "assembled-archive", ok: matches, expected: expectedArchive[1], actual: digest });
      ok = ok && matches;
    }
  }

  console.log(JSON.stringify({ ok, keyFingerprint: fingerprint(publicKey), checks }, null, 2));
  process.exit(ok ? 0 : 1);
}

function usage() {
  console.log(`STREAMIOV Release-Signatur (Ed25519, kostenlos)

  keygen [--key PATH] [--pub PATH]   Schlüsselpaar erzeugen
  sign <datei...> [--key PATH]       Dateien signieren (<datei>.sig)
  verify <datei...> [--pub PATH]     Signaturen prüfen
  sign-release [--key PATH] [--dir PATH]   SHA256SUMS-Dateien signieren
  verify-release [--pub PATH] [--dir PATH] Signaturen und Prüfsummen prüfen
  fingerprint [--pub PATH]           Fingerabdruck des öffentlichen Schlüssels

Privater Schlüssel (Standard): ${DEFAULT_KEY}
Öffentlicher Schlüssel (Standard): ${DEFAULT_PUB}
`);
}

function main() {
  const args = parseArgs(process.argv.slice(2));
  const command = args._.shift();
  if (args.help || !command) {
    usage();
    return;
  }
  if (command === "keygen") return keygen(args);
  if (command === "sign-release") return signRelease(args);
  if (command === "verify-release") return verifyRelease(args);
  if (command === "fingerprint") {
    const publicKey = readPublicKey(path.resolve(args.pub || DEFAULT_PUB));
    console.log(fingerprint(publicKey));
    return;
  }
  if (command === "sign") {
    if (!args._.length) fail("sign benötigt mindestens eine Datei");
    const privateKey = readKey(path.resolve(args.key || DEFAULT_KEY));
    for (const file of args._) {
      const abs = path.resolve(file);
      if (!fs.existsSync(abs)) fail(`Datei fehlt: ${file}`);
      signFile(abs, privateKey);
      console.log(`signiert: ${abs} -> ${signaturePath(abs)}`);
    }
    return;
  }
  if (command === "verify") {
    if (!args._.length) fail("verify benötigt mindestens eine Datei");
    const publicKey = readPublicKey(path.resolve(args.pub || DEFAULT_PUB));
    let ok = true;
    for (const file of args._) {
      const result = verifyFile(path.resolve(file), publicKey);
      ok = ok && result.ok;
      console.log(`${result.ok ? "OK" : "FEHLER"}: ${result.file}${result.error ? ` (${result.error})` : ""}`);
    }
    process.exit(ok ? 0 : 1);
  }
  fail(`Unbekannter Befehl: ${command}`);
}

main();
