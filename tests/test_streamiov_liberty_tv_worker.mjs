import test from "node:test";
import assert from "node:assert/strict";
import worker from "../infrastructure/cloudflare/streamiov-liberty-tv-worker/src/index.mjs";

test("health endpoint returns service identity and security headers", async () => {
  const response = await worker.fetch(new Request("https://example.test/healthz"), {});
  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), {
    service: "streamiov-liberty-tv-core",
    status: "ok",
    mode: "static-site-host"
  });
  assert.equal(response.headers.get("x-content-type-options"), "nosniff");
  assert.equal(response.headers.get("x-frame-options"), "DENY");
  assert.match(response.headers.get("content-security-policy"), /default-src 'self'/);
});

test("static requests are delegated to the dedicated assets binding", async () => {
  let seenUrl = "";
  const env = {
    ASSETS: {
      async fetch(request) {
        seenUrl = request.url;
        return new Response("liberty-site", { headers: { "content-type": "text/plain" } });
      }
    }
  };
  const response = await worker.fetch(new Request("https://example.test/"), env);
  assert.equal(seenUrl, "https://example.test/");
  assert.equal(await response.text(), "liberty-site");
  assert.equal(response.headers.get("referrer-policy"), "strict-origin-when-cross-origin");
});

test("missing asset binding fails closed with 503", async () => {
  const response = await worker.fetch(new Request("https://example.test/"), {});
  assert.equal(response.status, 503);
  assert.match(await response.text(), /binding is not configured/);
});
