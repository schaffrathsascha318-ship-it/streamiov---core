import { createCipheriv, createDecipheriv, hkdfSync, randomBytes } from "node:crypto";
import { readFile, writeFile, unlink } from "node:fs/promises";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";

const MAGIC = Buffer.from("STMIv1", "ascii");
const IV_BYTES = 12;
const TAG_BYTES = 16;

function deriveKey(secret, repository) {
  if (typeof secret !== "string" || secret.length < 32) {
    throw new Error("Mission-state encryption requires the configured high-entropy AI worker secret.");
  }
  if (typeof repository !== "string" || !repository.trim()) {
    throw new Error("Mission-state encryption requires the repository scope.");
  }
  return Buffer.from(hkdfSync(
    "sha256",
    Buffer.from(secret, "utf8"),
    Buffer.from("STREAMIOV-AI-MISSION-STATE-SALT-v1", "utf8"),
    Buffer.from(repository, "utf8"),
    32,
  ));
}

export function encryptBuffer(plaintext, secret, repository) {
  if (!Buffer.isBuffer(plaintext)) throw new TypeError("Mission state must be a Buffer.");
  const key = deriveKey(secret, repository);
  const iv = randomBytes(IV_BYTES);
  const cipher = createCipheriv("aes-256-gcm", key, iv);
  const ciphertext = Buffer.concat([cipher.update(plaintext), cipher.final()]);
  return Buffer.concat([MAGIC, iv, cipher.getAuthTag(), ciphertext]);
}

export function decryptBuffer(envelope, secret, repository) {
  if (!Buffer.isBuffer(envelope) || envelope.length < MAGIC.length + IV_BYTES + TAG_BYTES) {
    throw new Error("Mission-state artifact is truncated.");
  }
  if (!envelope.subarray(0, MAGIC.length).equals(MAGIC)) {
    throw new Error("Mission-state artifact has an unknown format.");
  }
  const key = deriveKey(secret, repository);
  const ivStart = MAGIC.length;
  const tagStart = ivStart + IV_BYTES;
  const ciphertextStart = tagStart + TAG_BYTES;
  const iv = envelope.subarray(ivStart, tagStart);
  const tag = envelope.subarray(tagStart, ciphertextStart);
  const ciphertext = envelope.subarray(ciphertextStart);
  const decipher = createDecipheriv("aes-256-gcm", key, iv);
  decipher.setAuthTag(tag);
  return Buffer.concat([decipher.update(ciphertext), decipher.final()]);
}

async function main() {
  const [mode, inputPath, outputPath] = process.argv.slice(2);
  if (!["encrypt", "decrypt"].includes(mode) || !inputPath || !outputPath) {
    throw new Error("Usage: mission-state-crypto.mjs <encrypt|decrypt> <input> <output>");
  }
  const secret = process.env.STREAMIOV_AI_WORKER_TOKEN;
  const repository = process.env.GITHUB_REPOSITORY;
  const input = await readFile(inputPath);
  const output = mode === "encrypt"
    ? encryptBuffer(input, secret, repository)
    : decryptBuffer(input, secret, repository);
  await writeFile(outputPath, output, { mode: 0o600 });
  await unlink(inputPath);
  process.stdout.write(`Mission state ${mode}ed successfully.\n`);
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main().catch((error) => {
    process.stderr.write(`Mission-state cryptography failed: ${error.message}\n`);
    process.exitCode = 1;
  });
}
