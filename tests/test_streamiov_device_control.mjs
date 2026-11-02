import test from "node:test";
import assert from "node:assert/strict";
import worker, { __test } from "../infrastructure/cloudflare/streamiov-device-control/src/index.mjs";

const ADMIN = "test-admin-token-with-at-least-thirty-two-characters";
const KEY_ENCRYPTION = __test.randomSecret(32);
const base = "https://device-control.test";

class MemoryD1 {
  constructor() { this.devices = new Map(); this.jobs = new Map(); }
  prepare(sql) {
    const db = this;
    return {
      bind(...values) {
        return {
          async first() { return db.first(sql, values); },
          async all() { return db.all(sql, values); },
          async run() { return db.run(sql, values); }
        };
      },
      async all() { return db.all(sql, []);
      }
    };
  }
  async first(sql, v) {
    if (sql.includes("FROM devices WHERE id = ?")) return this.devices.get(v[0]) || null;
    if (sql.includes("FROM jobs WHERE device_id = ? AND idempotency_key = ?")) {
      return [...this.jobs.values()].find((j) => j.device_id === v[0] && j.idempotency_key === v[1]) || null;
    }
    if (sql.includes("FROM jobs WHERE id = ? AND device_id = ?")) {
      const row = this.jobs.get(v[0]);
      return row?.device_id === v[1] ? row : null;
    }
    if (sql.includes("FROM jobs WHERE id = ?")) return this.jobs.get(v[0]) || null;
    if (sql.includes("UPDATE jobs SET status = 'claimed'")) {
      const [claimedAt, leaseExpiresAt, deviceId, now] = v;
      const row = [...this.jobs.values()]
        .filter((j) => j.device_id === deviceId && j.status === "queued" && j.expires_at >= now)
        .sort((a, b) => a.issued_at - b.issued_at)[0];
      if (!row) return null;
      Object.assign(row, { status: "claimed", claimed_at: claimedAt, lease_expires_at: leaseExpiresAt });
      return row;
    }
    if (sql.includes("UPDATE jobs SET status = ?, completed_at")) {
      const [status, completedAt, exitCode, duration, digest, output, completionDigest, id, deviceId] = v;
      const row = this.jobs.get(id);
      if (!row || row.device_id !== deviceId || row.status !== "claimed") return null;
      Object.assign(row, { status, completed_at: completedAt, exit_code: exitCode,
        duration_seconds: duration, result_sha256: digest, output, completion_digest: completionDigest });
      return { id };
    }
    return null;
  }
  async all(sql) {
    if (sql.includes("FROM devices")) return { results: [...this.devices.values()].map((d) => ({
      id: d.id, label: d.label, status: d.status, created_at: d.created_at,
      last_seen_at: d.last_seen_at, revoked_at: d.revoked_at
    })) };
    return { results: [] };
  }
  async run(sql, v) {
    if (sql.includes("INSERT INTO devices")) {
      const [id, label, tokenHash, encryptedKey, iv, createdAt] = v;
      this.devices.set(id, { id, label, status: "active", token_hash: tokenHash,
        encrypted_signing_key: encryptedKey, key_iv: iv, created_at: createdAt });
    } else if (sql.includes("INSERT INTO jobs")) {
      const [id, deviceId, profile, idempotency, reason, issuedAt, expiresAt, nonce] = v;
      this.jobs.set(id, { id, device_id: deviceId, profile, status: "queued",
        idempotency_key: idempotency, reason, issued_at: issuedAt, expires_at: expiresAt, nonce });
    } else if (sql.includes("SET status = 'uncertain' WHERE device_id")) {
      const [deviceId, now] = v;
      for (const row of this.jobs.values()) if (row.device_id === deviceId && row.status === "claimed" && row.lease_expires_at < now) row.status = "uncertain";
    } else if (sql.includes("SET status = 'expired'")) {
      const [deviceId, now] = v;
      for (const row of this.jobs.values()) if (row.device_id === deviceId && row.status === "queued" && row.expires_at < now) row.status = "expired";
    } else if (sql.includes("UPDATE devices SET last_seen_at")) {
      const [now, id] = v; const row = this.devices.get(id); if (row) row.last_seen_at = now;
    } else if (sql.includes("UPDATE devices SET status")) {
      const [status, revokedAt, id] = v; const row = this.devices.get(id);
      if (row && row.status !== "revoked") Object.assign(row, { status, revoked_at: revokedAt });
    } else if (sql.includes("SET status = 'uncertain' WHERE id")) {
      const [id] = v; const row = this.jobs.get(id); if (row?.status === "claimed") row.status = "uncertain";
    }
    return { success: true, meta: { changes: 1 } };
  }
}

function runtime(db = new MemoryD1()) {
  return { db, env: {
    DB: db,
    STREAMIOV_DEVICE_ADMIN_TOKEN: ADMIN,
    STREAMIOV_DEVICE_KEY_ENCRYPTION_KEY: KEY_ENCRYPTION
  }};
}

function request(path, { method = "GET", token, body } = {}) {
  return new Request(base + path, {
    method,
    headers: {
      ...(token ? { authorization: "Bearer " + token } : {}),
      ...(body !== undefined ? { "content-type": "application/json" } : {})
    },
    ...(body !== undefined ? { body: JSON.stringify(body) } : {})
  });
}

test("health is metadata-only and unknown routes fail closed", async () => {
  const { env } = runtime();
  const health = await worker.fetch(request("/health"), env);
  assert.equal(health.status, 200);
  assert.equal((await health.json()).service, "streamiov-device-control");
  const missing = await worker.fetch(request("/v1/nope"), env);
  assert.equal(missing.status, 404);
});

test("admin authentication and strict enrollment schema are enforced", async () => {
  const { env } = runtime();
  const denied = await worker.fetch(request("/v1/admin/devices", { token: "wrong" }), env);
  assert.equal(denied.status, 401);
  const extra = await worker.fetch(request("/v1/admin/devices/enroll", {
    method: "POST", token: ADMIN, body: { label: "chromebook", token: "attacker-controlled" }
  }), env);
  assert.equal(extra.status, 400);
});

test("enrollment stores only token hash and encrypted signing key", async () => {
  const { db, env } = runtime();
  const response = await worker.fetch(request("/v1/admin/devices/enroll", {
    method: "POST", token: ADMIN, body: { label: "chromebook-dev" }
  }), env);
  assert.equal(response.status, 201);
  const enrolled = await response.json();
  assert.equal(typeof enrolled.device_token, "string");
  assert.equal(typeof enrolled.signing_key, "string");
  const row = db.devices.get(enrolled.device_id);
  assert.ok(row);
  assert.notEqual(row.token_hash, enrolled.device_token);
  assert.notEqual(row.encrypted_signing_key, enrolled.signing_key);
  const listed = await worker.fetch(request("/v1/admin/devices", { token: ADMIN }), env);
  const text = await listed.text();
  assert.equal(text.includes(enrolled.device_token), false);
  assert.equal(text.includes(enrolled.signing_key), false);
});

test("fixed-profile job lifecycle is signed, device-bound and idempotent", async () => {
  const { db, env } = runtime();
  const enrollmentResponse = await worker.fetch(request("/v1/admin/devices/enroll", {
    method: "POST", token: ADMIN, body: { label: "test-device" }
  }), env);
  const enrollment = await enrollmentResponse.json();
  const submitted = {
    device_id: enrollment.device_id, profile: "diagnostics",
    idempotency_key: "test-job-key-0001", reason: "contract test"
  };
  const createdResponse = await worker.fetch(request("/v1/admin/jobs", {
    method: "POST", token: ADMIN, body: submitted
  }), env);
  assert.equal(createdResponse.status, 201);
  const created = await createdResponse.json();
  const duplicate = await worker.fetch(request("/v1/admin/jobs", {
    method: "POST", token: ADMIN, body: submitted
  }), env);
  assert.equal((await duplicate.json()).duplicate, true);

  const claimResponse = await worker.fetch(request("/v1/devices/" + enrollment.device_id + "/jobs/claim", {
    method: "POST", token: enrollment.device_token, body: { device_id: enrollment.device_id }
  }), env);
  assert.equal(claimResponse.status, 200);
  const envelope = await claimResponse.json();
  assert.equal(envelope.job.id, created.job.id);
  assert.deepEqual(envelope.job.args, {});
  const expectedSignature = await __test.signJob(envelope.job, enrollment.signing_key);
  assert.equal(envelope.signature, expectedSignature);

  const output = "Python 3 test output";
  const result = {
    job_id: envelope.job.id, device_id: enrollment.device_id, profile: "diagnostics",
    status: "succeeded", exit_code: 0, started_at: envelope.job.issued_at,
    finished_at: envelope.job.issued_at + 1, duration_seconds: 1,
    result_sha256: await __test.sha256Hex(output), output
  };
  const completePath = "/v1/devices/" + enrollment.device_id + "/jobs/" + envelope.job.id + "/complete";
  const completed = await worker.fetch(request(completePath, {
    method: "POST", token: enrollment.device_token, body: result
  }), env);
  assert.equal(completed.status, 200);
  assert.equal((await completed.json()).duplicate, false);
  const replay = await worker.fetch(request(completePath, {
    method: "POST", token: enrollment.device_token, body: result
  }), env);
  assert.equal((await replay.json()).duplicate, true);
  assert.equal(db.jobs.get(envelope.job.id).status, "succeeded");
});

test("unknown profiles and revoked devices cannot execute jobs", async () => {
  const { env } = runtime();
  const enrolled = await worker.fetch(request("/v1/admin/devices/enroll", {
    method: "POST", token: ADMIN, body: { label: "revocation-test" }
  }), env);
  const device = await enrolled.json();
  const badJob = await worker.fetch(request("/v1/admin/jobs", {
    method: "POST", token: ADMIN, body: {
      device_id: device.device_id, profile: "arbitrary-shell",
      idempotency_key: "bad-profile-0001", reason: "must reject"
    }
  }), env);
  assert.equal(badJob.status, 400);
  const revoked = await worker.fetch(request("/v1/admin/devices/" + device.device_id + "/revoke", {
    method: "POST", token: ADMIN
  }), env);
  assert.equal(revoked.status, 200);
  const claim = await worker.fetch(request("/v1/devices/" + device.device_id + "/jobs/claim", {
    method: "POST", token: device.device_token, body: { device_id: device.device_id }
  }), env);
  assert.equal(claim.status, 403);
});

test("completion rejects an invalid output digest", async () => {
  const { env } = runtime();
  const enrolled = await worker.fetch(request("/v1/admin/devices/enroll", {
    method: "POST", token: ADMIN, body: { label: "digest-test" }
  }), env);
  const device = await enrolled.json();
  const created = await worker.fetch(request("/v1/admin/jobs", {
    method: "POST", token: ADMIN, body: {
      device_id: device.device_id, profile: "git-status",
      idempotency_key: "digest-job-0001", reason: "digest validation"
    }
  }), env);
  const job = (await created.json()).job;
  await worker.fetch(request("/v1/devices/" + device.device_id + "/jobs/claim", {
    method: "POST", token: device.device_token, body: { device_id: device.device_id }
  }), env);
  const bad = await worker.fetch(request("/v1/devices/" + device.device_id + "/jobs/" + job.id + "/complete", {
    method: "POST", token: device.device_token, body: {
      job_id: job.id, device_id: device.device_id, profile: "git-status",
      status: "succeeded", exit_code: 0, started_at: job.issued_at,
      finished_at: job.issued_at + 1, duration_seconds: 1,
      result_sha256: "0".repeat(64), output: "not matching"
    }
  }), env);
  assert.equal(bad.status, 400);
});
