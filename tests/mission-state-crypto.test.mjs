import test from "node:test";
import assert from "node:assert/strict";
import { encryptBuffer, decryptBuffer } from "../scripts/autonomous/mission-state-crypto.mjs";

const secret = "test-only-high-entropy-secret-value-0123456789";
const repository = "streamiov-test/mission-state";

test("mission state encryption round-trips and uses a fresh nonce", () => {
  const plaintext = Buffer.from("private mission and agent checkpoint state", "utf8");
  const first = encryptBuffer(plaintext, secret, repository);
  const second = encryptBuffer(plaintext, secret, repository);
  assert.deepEqual(decryptBuffer(first, secret, repository), plaintext);
  assert.deepEqual(decryptBuffer(second, secret, repository), plaintext);
  assert.notDeepEqual(first, second);
  assert.equal(first.subarray(0, 6).toString("ascii"), "STMIv1");
});

test("mission state authentication rejects modified ciphertext", () => {
  const envelope = encryptBuffer(Buffer.from("checkpoint"), secret, repository);
  envelope[envelope.length - 1] ^= 0x01;
  assert.throws(() => decryptBuffer(envelope, secret, repository));
});

test("mission state authentication rejects a different secret or repository", () => {
  const envelope = encryptBuffer(Buffer.from("checkpoint"), secret, repository);
  assert.throws(() => decryptBuffer(envelope, "another-high-entropy-secret-value-0123456789", repository));
  assert.throws(() => decryptBuffer(envelope, secret, "another/repository"));
});

test("mission state encryption fails closed without a high-entropy secret", () => {
  assert.throws(() => encryptBuffer(Buffer.from("checkpoint"), "short", repository));
  assert.throws(() => encryptBuffer(Buffer.from("checkpoint"), secret, ""));
});

test("mission state decryption rejects truncated or unknown envelopes", () => {
  assert.throws(() => decryptBuffer(Buffer.from("short"), secret, repository));
  assert.throws(() => decryptBuffer(Buffer.concat([Buffer.from("BADBAD"), Buffer.alloc(40)]), secret, repository));
});
