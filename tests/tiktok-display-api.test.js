"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const { TikTokDisplayApi, BASIC_FIELDS, USER_INFO_ENDPOINT } = require("../core/integration/tiktok-display-api");

function fixture({ tokens, refreshTokens, fetchResponse, fetchImpl } = {}) {
  let current = Object.prototype.hasOwnProperty.call(arguments[0] || {}, "tokens") ? tokens : {
    access_token: "access-secret",
    refresh_token: "refresh-secret",
    scope: "user.info.basic",
    expires_at: Date.now() + 3600000
  };
  let refreshes = 0;
  const calls = [];
  const oauth = {
    store: { load: () => current },
    refresh: async () => {
      refreshes += 1;
      if (refreshTokens) current = refreshTokens;
    }
  };
  const fetch = fetchImpl || (async (url, options) => {
    calls.push({ url, options });
    return fetchResponse || {
      ok: true,
      json: async () => ({
        data: { user: { open_id: "open-123", display_name: "Creator", avatar_url: "https://example.test/avatar.jpg" } },
        error: { code: "ok", message: "" }
      })
    };
  });
  return { api: new TikTokDisplayApi({ oauth, fetch }), calls, getRefreshes: () => refreshes };
}

test("requests only basic profile fields and returns a token-free profile", async () => {
  const { api, calls } = fixture();
  const profile = await api.getCurrentUser();
  assert.deepEqual(BASIC_FIELDS, ["open_id", "display_name", "avatar_url"]);
  assert.equal(calls.length, 1);
  assert.equal(new URL(calls[0].url).origin + new URL(calls[0].url).pathname, USER_INFO_ENDPOINT);
  assert.equal(new URL(calls[0].url).searchParams.get("fields"), "open_id,display_name,avatar_url");
  assert.equal(calls[0].options.method, "GET");
  assert.equal(calls[0].options.headers.Authorization, "Bearer access-secret");
  assert.deepEqual(profile, {
    openId: "open-123",
    displayName: "Creator",
    avatarUrl: "https://example.test/avatar.jpg"
  });
  assert.equal(JSON.stringify(profile).includes("access-secret"), false);
  assert.equal(JSON.stringify(profile).includes("refresh-secret"), false);
});

test("refreshes an expiring token before requesting the profile", async () => {
  const { api, getRefreshes, calls } = fixture({
    tokens: { access_token: "old", refresh_token: "r1", scope: "user.info.basic", expires_at: 0 },
    refreshTokens: { access_token: "new", refresh_token: "r2", scope: "user.info.basic", expires_at: Date.now() + 3600000 }
  });
  await api.getCurrentUser();
  assert.equal(getRefreshes(), 1);
  assert.equal(calls[0].options.headers.Authorization, "Bearer new");
});

test("rejects disconnected accounts and missing basic scope", async () => {
  const disconnected = fixture({ tokens: null });
  await assert.rejects(() => disconnected.api.getCurrentUser(), /tiktok_account_not_connected/);
  const missingScope = fixture({ tokens: { access_token: "a", scope: "video.list", expires_at: Date.now() + 3600000 } });
  await assert.rejects(() => missingScope.api.getCurrentUser(), /tiktok_basic_profile_scope_missing/);
});

test("rejects provider errors and malformed profiles without leaking details", async () => {
  const failed = fixture({ fetchResponse: { ok: true, json: async () => ({ error: { code: "scope_not_authorized", message: "private provider text" } }) } });
  await assert.rejects(() => failed.api.getCurrentUser(), /tiktok_display_api_request_failed/);
  const malformed = fixture({ fetchResponse: { ok: true, json: async () => ({ data: { user: {} }, error: { code: "ok" } }) } });
  await assert.rejects(() => malformed.api.getCurrentUser(), /tiktok_display_api_profile_missing/);
});
