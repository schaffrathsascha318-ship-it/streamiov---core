import test from "node:test";
import assert from "node:assert/strict";
import { runD1Backup, getTimeTravelBookmark } from "../infrastructure/cloudflare/d1-backup/src/backup-manager.mjs";

const token = "test-token-never-logged";
function makeEnv(overrides = {}) {
  const objects = new Map();
  return {
    CLOUDFLARE_ACCOUNT_ID: "account123",
    D1_DATABASE_ID: "database123",
    D1_REST_API_TOKEN: token,
    BACKUPS: {
      async put(key, value, options = {}) { objects.set(key, { bytes: typeof value === "string" ? new TextEncoder().encode(value) : new Uint8Array(value), customMetadata: options.customMetadata || {} }); },
      async get(key) { const o = objects.get(key); return o ? { arrayBuffer: async () => o.bytes.buffer.slice(o.bytes.byteOffset, o.bytes.byteOffset + o.bytes.byteLength) } : null; },
      async head(key) { const o = objects.get(key); return o ? { size: o.bytes.byteLength, customMetadata: o.customMetadata } : null; },
      objects
    },
    ...overrides
  };
}
function response(result) { return new Response(JSON.stringify({ success: true, result }), { status: 200 }); }

test("exports, polls, uploads and read-back verifies a D1 SQL dump", async () => {
  const env = makeEnv();
  const calls = [];
  const fetchImpl = async (url, init = {}) => {
    calls.push({ url: String(url), init });
    if (String(url).includes("/export")) {
      const body = JSON.parse(init.body);
      if (!body.current_bookmark) return response({ at_bookmark: "bookmark-001", status: "pending" });
      return response({ at_bookmark: "bookmark-001", status: "complete", result: { signed_url: "https://download.example/dump.sql" } });
    }
    return new Response("CREATE TABLE sample (id INTEGER);", { status: 200 });
  };
  const result = await runD1Backup(env, { fetchImpl, sleep: async () => {}, now: () => new Date("2026-11-22T00:00:00.000Z") });
  assert.equal(result.at_bookmark, "bookmark-001");
  assert.equal(result.verification, "r2-readback-sha256-verified");
  assert.equal(env.BACKUPS.objects.has(result.object_key), true);
  assert.equal(env.BACKUPS.objects.has(result.manifest_key), true);
  assert.equal(calls.length, 3);
  assert.equal(calls[0].init.headers.authorization, `Bearer ${token}`);
  assert.equal(calls[1].init.body.includes("bookmark-001"), true);
  assert.equal(calls.some((call) => JSON.stringify(call).includes(token)), false);
});

test("fails closed on export API errors and does not create an R2 object", async () => {
  const env = makeEnv();
  await assert.rejects(runD1Backup(env, { fetchImpl: async () => new Response(JSON.stringify({ success: false, errors: [{ code: 10000 }] }), { status: 200 }) }), /Cloudflare API rejected/);
  assert.equal(env.BACKUPS.objects.size, 0);
});

test("rejects export without bookmark, failed polling, and polling timeout", async () => {
  const env = makeEnv();
  await assert.rejects(runD1Backup(env, { fetchImpl: async () => response({ status: "pending" }) }), /at_bookmark/);
  let count = 0;
  await assert.rejects(runD1Backup(env, { maxPolls: 1, fetchImpl: async () => { count++; return response({ at_bookmark: "b", status: "pending" }); }, sleep: async () => {} }), /timed out/);
  assert.equal(count, 2);
  await assert.rejects(runD1Backup(env, { fetchImpl: async () => response({ at_bookmark: "b", status: "error", error: "failure" }) }), /failed/);
});

test("rejects missing configuration and oversized or empty dumps", async () => {
  await assert.rejects(runD1Backup(makeEnv({ D1_DATABASE_ID: "" })), /D1_DATABASE_ID/);
  const env = makeEnv();
  await assert.rejects(runD1Backup(env, { fetchImpl: async (url) => String(url).includes("/export") ? response({ at_bookmark: "b", status: "complete", result: { signed_url: "https://download.example/dump" } }) : new Response("large", { status: 200 }), maxBytes: 2 }), /safety limit/);
});

test("captures a D1 Time Travel bookmark without exposing credentials", async () => {
  const result = await getTimeTravelBookmark(makeEnv(), { fetchImpl: async (_url, init) => {
    assert.equal(init.headers.authorization, `Bearer ${token}`);
    return new Response(JSON.stringify({ success: true, result: { bookmark: "tt-bookmark" } }), { status: 200 });
  }});
  assert.equal(result.bookmark, "tt-bookmark");
  assert.ok(result.captured_at);
});
