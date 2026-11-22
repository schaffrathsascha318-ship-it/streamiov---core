"use strict";

const USER_INFO_ENDPOINT = "https://open.tiktokapis.com/v2/user/info/";
const BASIC_FIELDS = Object.freeze(["open_id", "display_name", "avatar_url"]);

function providerError(payload) {
  const error = payload && payload.error;
  if (!error) return null;
  const code = error.code;
  if (code === "ok" || code === 0 || code === "0") return null;
  return new Error("tiktok_display_api_request_failed");
}

/**
 * Reads only the TikTok profile fields covered by user.info.basic.
 * The OAuth instance owns token encryption, refresh and revocation.
 */
class TikTokDisplayApi {
  constructor({ oauth, fetch: fetchImpl, clock = Date.now, refreshSkewMs = 300000 } = {}) {
    if (!oauth || !oauth.store || typeof oauth.refresh !== "function") {
      throw new Error("tiktok_oauth_service_required");
    }
    this.oauth = oauth;
    this.fetch = fetchImpl || globalThis.fetch;
    this.clock = clock;
    this.refreshSkewMs = refreshSkewMs;
    if (typeof this.fetch !== "function") throw new Error("fetch_unavailable");
  }

  async _accessToken() {
    let tokens = this.oauth.store.load();
    if (!tokens || typeof tokens.access_token !== "string" || !tokens.access_token) {
      throw new Error("tiktok_account_not_connected");
    }
    const scopes = String(tokens.scope || "").split(/[ ,]+/).filter(Boolean);
    if (!scopes.includes("user.info.basic")) {
      throw new Error("tiktok_basic_profile_scope_missing");
    }
    if (Number(tokens.expires_at) <= this.clock() + this.refreshSkewMs) {
      await this.oauth.refresh();
      tokens = this.oauth.store.load();
      if (!tokens || typeof tokens.access_token !== "string" || !tokens.access_token ||
          Number(tokens.expires_at) <= this.clock()) {
        throw new Error("tiktok_access_token_unavailable");
      }
    }
    return tokens.access_token;
  }

  async getCurrentUser() {
    const accessToken = await this._accessToken();
    const url = new URL(USER_INFO_ENDPOINT);
    url.searchParams.set("fields", BASIC_FIELDS.join(","));
    const response = await this.fetch(url.toString(), {
      method: "GET",
      headers: {
        Authorization: "Bearer " + accessToken,
        Accept: "application/json",
        "Cache-Control": "no-store"
      }
    });
    let payload;
    try {
      payload = await response.json();
    } catch (_) {
      throw new Error("tiktok_display_api_invalid_response");
    }
    if (!response.ok) throw new Error("tiktok_display_api_request_failed");
    const apiError = providerError(payload);
    if (apiError) throw apiError;
    const user = payload && payload.data && payload.data.user;
    if (!user || typeof user.open_id !== "string" || !user.open_id) {
      throw new Error("tiktok_display_api_profile_missing");
    }
    return {
      openId: user.open_id,
      displayName: typeof user.display_name === "string" ? user.display_name : null,
      avatarUrl: typeof user.avatar_url === "string" ? user.avatar_url : null
    };
  }
}

module.exports = { TikTokDisplayApi, BASIC_FIELDS, USER_INFO_ENDPOINT };
