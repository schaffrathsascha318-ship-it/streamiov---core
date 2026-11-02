const MAX_BODY_BYTES = 24 * 1024;
const MAX_OUTPUT_BYTES = 16 * 1024;
const MAX_JOB_TTL_SECONDS = 300;
const CLAIM_LEASE_SECONDS = 20 * 60;
const PROFILES = new Set(["diagnostics", "git-status", "python-tests"]);
const encoder = new TextEncoder();

function json(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
      "x-content-type-options": "nosniff",
      "referrer-policy": "no-referrer"
    }
  });
}

function constantTimeEqual(left, right) {
  const a = encoder.encode(String(left));
  const b = encoder.encode(String(right));
  let difference = a.length ^ b.length;
  for (let i = 0; i < Math.max(a.length, b.length); i += 1) {
    difference |= (a[i] || 0) ^ (b[i] || 0);
  }
  return difference === 0;
}

function canonical(value) {
  if (value === null || typeof value !== "object") return JSON.stringify(value);
  if (Array.isArray(value)) return "[" + value.map(canonical).join(",") + "]";
  return "{" + Object.keys(value).sort().map((key) => JSON.stringify(key) + ":" + canonical(value[key])).join(",") + "}";
}

function base64url(bytes) {
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
}

function fromBase64url(value) {
  const normalized = value.replace(/-/g, "+").replace(/_/g, "/");
  const padded = normalized + "=".repeat((4 - normalized.length % 4) % 4);
  const binary = atob(padded);
  return Uint8Array.from(binary, (char) => char.charCodeAt(0));
}

function randomSecret(bytes = 32) {
  const value = new Uint8Array(bytes);
  crypto.getRandomValues(value);
  return base64url(value);
}

async function sha256Hex(value) {
  const digest = await crypto.subtle.digest("SHA-256", typeof value === "string" ? encoder.encode(value) : value);
  return [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

function encryptionKey(env) {
  const configured = env.STREAMIOV_DEVICE_KEY_ENCRYPTION_KEY;
  if (typeof configured !== "string" || configured.length < 40) throw new Error("encryption-key-not-configured");
  const bytes = fromBase64url(configured);
  if (bytes.byteLength !== 32) throw new Error("invalid-encryption-key");
  return crypto.subtle.importKey("raw", bytes, "AES-GCM", false, ["encrypt", "decrypt"]);
}

async function encryptSigningKey(signingKey, env) {
  const key = await encryptionKey(env);
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const ciphertext = await crypto.subtle.encrypt({ name: "AES-GCM", iv }, key, encoder.encode(signingKey));
  return { ciphertext: base64url(new Uint8Array(ciphertext)), iv: base64url(iv) };
}

async function decryptSigningKey(row, env) {
  const key = await encryptionKey(env);
  const plaintext = await crypto.subtle.decrypt(
    { name: "AES-GCM", iv: fromBase64url(row.key_iv) },
    key,
    fromBase64url(row.encrypted_signing_key)
  );
  return new TextDecoder().decode(plaintext);
}

async function signJob(job, signingKey) {
  const key = await crypto.subtle.importKey(
    "raw", encoder.encode(signingKey), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]
  );
  const signature = await crypto.subtle.sign("HMAC", key, encoder.encode(canonical(job)));
  return [...new Uint8Array(signature)].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

async function readJsonLimited(request) {
  if (!(request.headers.get("content-type") || "").toLowerCase().startsWith("application/json")) {
    throw new Error("content-type");
  }
  const declared = Number(request.headers.get("content-length") || 0);
  if (declared > MAX_BODY_BYTES) throw new Error("body-too-large");
  if (!request.body) throw new Error("missing-body");
  const reader = request.body.getReader();
  const chunks = [];
  let size = 0;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    size += value.byteLength;
    if (size > MAX_BODY_BYTES) {
      await reader.cancel();
      throw new Error("body-too-large");
    }
    chunks.push(value);
  }
  const bytes = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  try {
    const value = JSON.parse(new TextDecoder().decode(bytes));
    if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("object-required");
    return value;
  } catch {
    throw new Error("invalid-json");
  }
}

function exactKeys(value, expected) {
  return value && typeof value === "object" && !Array.isArray(value) &&
    Object.keys(value).length === expected.length && expected.every((key) => Object.hasOwn(value, key));
}

function bearer(request) {
  const header = request.headers.get("authorization") || "";
  return header.startsWith("Bearer ") ? header.slice(7) : "";
}

async function requireAdmin(request, env) {
  const expected = env.STREAMIOV_DEVICE_ADMIN_TOKEN;
  if (typeof expected !== "string" || expected.length < 32) return { error: json({ error: "service_not_configured" }, 503) };
  const supplied = bearer(request);
  if (!supplied || !constantTimeEqual(await sha256Hex(supplied), await sha256Hex(expected))) {
    return { error: json({ error: "unauthorized" }, 401) };
  }
  return { ok: true };
}

async function requireDevice(request, env, deviceId) {
  if (!env.DB) return { error: json({ error: "service_not_configured" }, 503) };
  const token = bearer(request);
  if (token.length < 32) return { error: json({ error: "unauthorized" }, 401) };
  const row = await env.DB.prepare(
    "SELECT id, status, token_hash, encrypted_signing_key, key_iv FROM devices WHERE id = ?"
  ).bind(deviceId).first();
  if (!row || !constantTimeEqual(await sha256Hex(token), row.token_hash)) {
    return { error: json({ error: "unauthorized" }, 401) };
  }
  if (row.status !== "active") return { error: json({ error: "device_not_active" }, 403) };
  return { device: row };
}

function publicJob(row) {
  return {
    id: row.id,
    device_id: row.device_id,
    profile: row.profile,
    status: row.status,
    issued_at: row.issued_at,
    expires_at: row.expires_at,
    claimed_at: row.claimed_at,
    completed_at: row.completed_at,
    exit_code: row.exit_code,
    result_sha256: row.result_sha256
  };
}

function validId(value) {
  return typeof value === "string" && /^[A-Za-z0-9_-]{8,80}$/.test(value);
}

async function adminRoute(request, env, url, segments) {
  const auth = await requireAdmin(request, env);
  if (auth.error) return auth.error;
  if (!env.DB) return json({ error: "database_not_configured" }, 503);

  if (segments[2] === "devices" && segments.length === 3 && request.method === "GET") {
    const result = await env.DB.prepare(
      "SELECT id, label, status, created_at, last_seen_at, revoked_at FROM devices ORDER BY created_at DESC LIMIT 100"
    ).all();
    return json({ devices: result.results || [] });
  }

  if (segments[2] === "devices" && segments[3] === "enroll" && segments.length === 4 && request.method === "POST") {
    let body;
    try { body = await readJsonLimited(request); } catch { return json({ error: "invalid_request" }, 400); }
    if (!exactKeys(body, ["label"]) || typeof body.label !== "string" || body.label.trim().length < 1 || body.label.length > 80) {
      return json({ error: "invalid_request" }, 400);
    }
    if (typeof env.STREAMIOV_DEVICE_KEY_ENCRYPTION_KEY !== "string") return json({ error: "service_not_configured" }, 503);
    const id = crypto.randomUUID().replace(/-/g, "");
    const token = randomSecret(32);
    const signingKey = randomSecret(32);
    let encrypted;
    try { encrypted = await encryptSigningKey(signingKey, env); } catch { return json({ error: "service_not_configured" }, 503); }
    const now = Math.floor(Date.now() / 1000);
    await env.DB.prepare(
      "INSERT INTO devices (id, label, status, token_hash, encrypted_signing_key, key_iv, created_at) VALUES (?, ?, 'active', ?, ?, ?, ?)"
    ).bind(id, body.label.trim(), await sha256Hex(token), encrypted.ciphertext, encrypted.iv, now).run();
    // Credentials are returned exactly once. Never log or persist this response.
    return json({ device_id: id, control_plane: url.origin, device_token: token, signing_key: signingKey, status: "active" }, 201);
  }

  if (segments[2] === "devices" && segments.length === 5 && ["pause", "resume", "revoke"].includes(segments[4]) && request.method === "POST") {
    const id = segments[3];
    if (!validId(id)) return json({ error: "not_found" }, 404);
    const row = await env.DB.prepare("SELECT id, status FROM devices WHERE id = ?").bind(id).first();
    if (!row) return json({ error: "not_found" }, 404);
    if (row.status === "revoked") return json({ error: "device_revoked" }, 409);
    const status = segments[4] === "pause" ? "paused" : segments[4] === "resume" ? "active" : "revoked";
    const now = Math.floor(Date.now() / 1000);
    await env.DB.prepare(
      "UPDATE devices SET status = ?, revoked_at = ? WHERE id = ? AND status != 'revoked'"
    ).bind(status, status === "revoked" ? now : null, id).run();
    return json({ device_id: id, status });
  }

  if (segments[2] === "jobs" && segments.length === 3 && request.method === "POST") {
    let body;
    try { body = await readJsonLimited(request); } catch { return json({ error: "invalid_request" }, 400); }
    if (!exactKeys(body, ["device_id", "profile", "idempotency_key", "reason"]) ||
        !validId(body.device_id) || !PROFILES.has(body.profile) ||
        typeof body.idempotency_key !== "string" || !/^[A-Za-z0-9_-]{8,100}$/.test(body.idempotency_key) ||
        typeof body.reason !== "string" || body.reason.trim().length < 1 || body.reason.length > 240) {
      return json({ error: "invalid_request" }, 400);
    }
    const device = await env.DB.prepare(
      "SELECT id, status, encrypted_signing_key, key_iv FROM devices WHERE id = ?"
    ).bind(body.device_id).first();
    if (!device || device.status !== "active") return json({ error: "device_not_active" }, 409);
    const prior = await env.DB.prepare(
      "SELECT * FROM jobs WHERE device_id = ? AND idempotency_key = ?"
    ).bind(body.device_id, body.idempotency_key).first();
    if (prior) return json({ job: publicJob(prior), duplicate: true }, 200);
    const now = Math.floor(Date.now() / 1000);
    const job = {
      id: crypto.randomUUID().replace(/-/g, ""),
      device_id: body.device_id,
      profile: body.profile,
      issued_at: now,
      expires_at: now + MAX_JOB_TTL_SECONDS,
      nonce: randomSecret(24),
      args: {}
    };
    let signingKey;
    try { signingKey = await decryptSigningKey(device, env); } catch { return json({ error: "device_key_unavailable" }, 503); }
    const signature = await signJob(job, signingKey);
    try {
      await env.DB.prepare(
        "INSERT INTO jobs (id, device_id, profile, status, idempotency_key, reason, issued_at, expires_at, nonce) VALUES (?, ?, ?, 'queued', ?, ?, ?, ?, ?)"
      ).bind(job.id, job.device_id, job.profile, body.idempotency_key, body.reason.trim(), job.issued_at, job.expires_at, job.nonce).run();
    } catch {
      const raced = await env.DB.prepare(
        "SELECT * FROM jobs WHERE device_id = ? AND idempotency_key = ?"
      ).bind(body.device_id, body.idempotency_key).first();
      if (raced) return json({ job: publicJob(raced), duplicate: true }, 200);
      return json({ error: "job_not_created" }, 409);
    }
    return json({ job: publicJob({ ...job, status: "queued" }), duplicate: false }, 201);
  }

  if (segments[2] === "jobs" && segments.length === 4 && request.method === "GET") {
    const row = await env.DB.prepare("SELECT * FROM jobs WHERE id = ?").bind(segments[3]).first();
    return row ? json({ job: publicJob(row) }) : json({ error: "not_found" }, 404);
  }
  return json({ error: "not_found" }, 404);
}

async function deviceRoute(request, env, segments) {
  const deviceId = segments[2];
  if (!validId(deviceId)) return json({ error: "not_found" }, 404);
  const auth = await requireDevice(request, env, deviceId);
  if (auth.error) return auth.error;
  if (segments[3] !== "jobs" || segments.length < 5) return json({ error: "not_found" }, 404);

  if (segments[4] === "claim" && segments.length === 5 && request.method === "POST") {
    let body;
    try { body = await readJsonLimited(request); } catch { return json({ error: "invalid_request" }, 400); }
    if (!exactKeys(body, ["device_id"]) || body.device_id !== deviceId) return json({ error: "invalid_request" }, 400);
    const now = Math.floor(Date.now() / 1000);
    // Expired claims become uncertain. They are deliberately never requeued.
    await env.DB.prepare(
      "UPDATE jobs SET status = 'uncertain' WHERE device_id = ? AND status = 'claimed' AND lease_expires_at < ?"
    ).bind(deviceId, now).run();
    const row = await env.DB.prepare(
      "UPDATE jobs SET status = 'claimed', claimed_at = ?, lease_expires_at = ? WHERE id = (SELECT id FROM jobs WHERE device_id = ? AND status = 'queued' ORDER BY issued_at ASC LIMIT 1) AND status = 'queued' RETURNING *"
    ).bind(now, now + CLAIM_LEASE_SECONDS, deviceId).first();
    if (!row) {
      await env.DB.prepare("UPDATE devices SET last_seen_at = ? WHERE id = ?").bind(now, deviceId).run();
      return json({ status: "idle" });
    }
    const job = {
      id: row.id, device_id: row.device_id, profile: row.profile,
      issued_at: row.issued_at, expires_at: row.expires_at, nonce: row.nonce, args: {}
    };
    const signingKey = await decryptSigningKey(auth.device, env);
    return json({ job, signature: await signJob(job, signingKey) });
  }

  if (segments[4] === "complete" && segments.length === 6 && request.method === "POST") {
    const jobId = segments[5];
    if (!validId(jobId)) return json({ error: "not_found" }, 404);
    let body;
    try { body = await readJsonLimited(request); } catch { return json({ error: "invalid_request" }, 400); }
    const required = ["job_id", "device_id", "profile", "status", "exit_code", "started_at", "finished_at", "duration_seconds", "result_sha256", "output"];
    if (!exactKeys(body, required) || body.job_id !== jobId || body.device_id !== deviceId ||
        !PROFILES.has(body.profile) || !["succeeded", "failed"].includes(body.status) ||
        !Number.isInteger(body.exit_code) || !Number.isInteger(body.started_at) ||
        !Number.isInteger(body.finished_at) || !Number.isInteger(body.duration_seconds) ||
        body.duration_seconds < 0 || typeof body.output !== "string" ||
        encoder.encode(body.output).byteLength > MAX_OUTPUT_BYTES ||
        typeof body.result_sha256 !== "string" || !/^[a-f0-9]{64}$/.test(body.result_sha256)) {
      return json({ error: "invalid_request" }, 400);
    }
    if (await sha256Hex(body.output) !== body.result_sha256) return json({ error: "digest_mismatch" }, 400);
    const row = await env.DB.prepare("SELECT * FROM jobs WHERE id = ? AND device_id = ?").bind(jobId, deviceId).first();
    if (!row) return json({ error: "not_found" }, 404);
    const completionDigest = await sha256Hex(canonical(body));
    if (["succeeded", "failed"].includes(row.status)) {
      if (row.completion_digest && constantTimeEqual(row.completion_digest, completionDigest)) {
        return json({ status: "completed", duplicate: true });
      }
      return json({ error: "completion_conflict" }, 409);
    }
    const now = Math.floor(Date.now() / 1000);
    if (row.status !== "claimed" || !row.lease_expires_at || row.lease_expires_at < now) {
      if (row.status === "claimed") {
        await env.DB.prepare("UPDATE jobs SET status = 'uncertain' WHERE id = ? AND status = 'claimed'").bind(jobId).run();
      }
      return json({ error: "job_not_completable" }, 409);
    }
    if (body.profile !== row.profile) return json({ error: "profile_mismatch" }, 400);
    await env.DB.prepare(
      "UPDATE jobs SET status = ?, completed_at = ?, exit_code = ?, duration_seconds = ?, result_sha256 = ?, output = ?, completion_digest = ? WHERE id = ? AND device_id = ? AND status = 'claimed'"
    ).bind(body.status, now, body.exit_code, body.duration_seconds, body.result_sha256, body.output, completionDigest, jobId, deviceId).run();
    return json({ status: "completed", duplicate: false });
  }
  return json({ error: "not_found" }, 404);
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const segments = url.pathname.split("/").filter(Boolean);
    if (url.pathname === "/health" && request.method === "GET") {
      return json({ ok: true, service: "streamiov-device-control", mode: "control-plane" });
    }
    if (segments[0] !== "v1") return json({ error: "not_found" }, 404);
    if (segments[1] === "admin") {
      if (!["GET", "POST"].includes(request.method)) return json({ error: "method_not_allowed" }, 405);
      return adminRoute(request, env, url, segments);
    }
    if (segments[1] === "devices") {
      if (request.method !== "POST") return json({ error: "method_not_allowed" }, 405);
      return deviceRoute(request, env, segments);
    }
    return json({ error: "not_found" }, 404);
  }
};

export const __test = { canonical, constantTimeEqual, exactKeys, randomSecret, signJob, sha256Hex };
