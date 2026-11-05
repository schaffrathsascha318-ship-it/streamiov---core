"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { TikTokOAuthRegistry } = require("../core/integration/tiktok-oauth-registry");

function fixture() {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "streamiov-tiktok-registry-"));
  const env = {
    STREAMIOV_TIKTOK_SANDBOX_CLIENT_KEY: "sandbox-client-key",
    STREAMIOV_TIKTOK_SANDBOX_CLIENT_SECRET: "sandbox-client-secret",
    STREAMIOV_TIKTOK_SANDBOX_REDIRECT_URI: "http://127.0.0.1:8765/api/v1/platforms/tiktok/callback",
    STREAMIOV_TIKTOK_SANDBOX_TOKEN_ENCRYPTION_KEY: Buffer.alloc(32, 7).toString("base64")
  };
  const fetch = async (_url, options) => {
    const body = new URLSearchParams(options.body);
    assert.equal(body.get("client_key"), "sandbox-client-key");
    return {
      ok: true,
      async json() {
        return {
          access_token: "access-token-for-test",
          refresh_token: "refresh-token-for-test",
          expires_in: 3600,
          refresh_expires_in: 86400,
          scope: "user.info.basic",
          open_id: "provider-user"
        };
      }
    };
  };
  const registry = new TikTokOAuthRegistry({
    environment: "sandbox",
    env,
    tokenDirectory: path.join(directory, "tokens"),
    fetch
  });
  return { directory, registry };
}

test("OAuth registry isolates token files and status by authenticated account id", async (t) => {
  const { directory, registry } = fixture();
  t.after(() => fs.rmSync(directory, { recursive: true, force: true }));

  const first = registry.createAuthorizationUrl("user-001");
  const second = registry.createAuthorizationUrl("user-002");
  assert.notEqual(first.state, second.state);
  assert.match(first.url, /client_key=sandbox-client-key/);
  assert.match(second.url, /scope=user.info.basic/);

  const result = await registry.callback({ code: "authorization-code", state: first.state });
  assert.equal(result.accountId, "user-001");
  assert.equal(result.status, "connected");
  assert.equal(registry.status("user-001").status, "connected");
  assert.equal(registry.status("user-002").status, "not_connected");

  const files = fs.readdirSync(path.join(directory, "tokens"));
  assert.equal(files.length, 1);
  assert.match(files[0], /^[a-f0-9]{64}\.json$/);
  const stored = fs.readFileSync(path.join(directory, "tokens", files[0]), "utf8");
  assert.equal(stored.includes("access-token-for-test"), false);
  assert.equal(stored.includes("user-001"), false);
});

test("OAuth registry binds a callback to its original account and consumes state once", async (t) => {
  const { directory, registry } = fixture();
  t.after(() => fs.rmSync(directory, { recursive: true, force: true }));

  const authorization = registry.createAuthorizationUrl("creator-A");
  const connected = await registry.callback({ code: "authorization-code", state: authorization.state });
  assert.equal(connected.accountId, "creator-A");
  await assert.rejects(
    registry.callback({ code: "authorization-code", state: authorization.state }),
    /oauth_state_mismatch/
  );
  assert.equal(registry.status("creator-A").status, "connected");
  assert.equal(registry.status("creator-B").status, "not_connected");
});

test("OAuth registry rejects unsafe account identifiers and invalid environments", () => {
  const { directory, registry } = fixture();
  try {
    assert.throws(() => registry.status("../outside"), /account_id_invalid/);
    assert.throws(() => new TikTokOAuthRegistry({ environment: "staging" }), /invalid_oauth_environment/);
  } finally {
    fs.rmSync(directory, { recursive: true, force: true });
  }
});
