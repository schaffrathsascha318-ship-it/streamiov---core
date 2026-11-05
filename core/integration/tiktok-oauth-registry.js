"use strict";

const crypto = require("node:crypto");
const path = require("node:path");
const fs = require("node:fs");
const { TikTokOAuth } = require("./tiktok-oauth");

const ACCOUNT_ID_PATTERN = /^[A-Za-z0-9_-]{1,128}$/;
const MAX_PENDING_STATES = 4096;

/**
 * Owns one OAuth/token store per authenticated STREAMIOV account.
 *
 * The registry is process-local so PKCE state remains bound to the instance
 * that created it. Encrypted token files survive restarts; pending authorizing
 * sessions intentionally do not and must be restarted by the user.
 */
class TikTokOAuthRegistry {
  constructor(options = {}) {
    this.environment = options.environment || process.env.STREAMIOV_TIKTOK_ENVIRONMENT || "sandbox";
    if (!["sandbox", "production"].includes(this.environment)) {
      throw new Error("invalid_oauth_environment");
    }
    const prefix = this.environment === "sandbox"
      ? "STREAMIOV_TIKTOK_SANDBOX"
      : "STREAMIOV_TIKTOK_PRODUCTION";
    const env = options.env || process.env;
    this.tokenDirectory = path.resolve(
      options.tokenDirectory ||
      env[prefix + "_TOKEN_DIRECTORY"] ||
      path.join(process.cwd(), "data", "oauth", "tiktok-" + this.environment, "accounts")
    );
    this.oauthOptions = {
      environment: this.environment,
      env,
      fetch: options.fetch,
      clock: options.clock,
      stateTtlMs: options.stateTtlMs,
      clientKey: options.clientKey,
      clientSecret: options.clientSecret,
      redirectUri: options.redirectUri,
      encryptionKey: options.encryptionKey
    };
    this.instances = new Map();
    this.pendingOwners = new Map();
    this.maxAccounts = Number.isInteger(options.maxAccounts) ? options.maxAccounts : 1000;
  }

  _accountId(accountId) {
    if (typeof accountId !== "string" || !ACCOUNT_ID_PATTERN.test(accountId)) {
      throw new Error("account_id_invalid");
    }
    return accountId;
  }

  _instance(accountId) {
    const id = this._accountId(accountId);
    let instance = this.instances.get(id);
    if (instance) return instance;
    if (this.instances.size >= this.maxAccounts) {
      throw new Error("oauth_account_capacity_reached");
    }
    const prefix = this.environment === "sandbox"
      ? "STREAMIOV_TIKTOK_SANDBOX"
      : "STREAMIOV_TIKTOK_PRODUCTION";
    const env = this.oauthOptions.env || process.env;
    const root = this.tokenDirectory;
    fs.mkdirSync(root, { recursive: true, mode: 0o700 });
    try { fs.chmodSync(root, 0o700); } catch (_) {}
    const accountHash = crypto.createHash("sha256").update(id, "utf8").digest("hex");
    const tokenFile = path.join(root, accountHash + ".json");
    instance = new TikTokOAuth({
      ...this.oauthOptions,
      tokenFile,
      env,
      environment: this.environment
    });
    this.instances.set(id, instance);
    return instance;
  }

  createAuthorizationUrl(accountId) {
    const id = this._accountId(accountId);
    this._prunePending();
    if (this.pendingOwners.size >= MAX_PENDING_STATES) {
      throw new Error("oauth_pending_capacity_reached");
    }
    const result = this._instance(id).createAuthorizationUrl();
    this.pendingOwners.set(result.state, { accountId: id, createdAt: Date.now() });
    return result;
  }

  async callback({ code, state, error } = {}) {
    if (typeof state !== "string" || !state) throw new Error("oauth_state_missing");
    this._prunePending();
    const pending = this.pendingOwners.get(state);
    this.pendingOwners.delete(state);
    if (!pending) throw new Error("oauth_state_mismatch");
    const result = await this._instance(pending.accountId).callback({ code, state, error });
    return { ...result, accountId: pending.accountId };
  }

  status(accountId) {
    return this._instance(accountId).status();
  }

  async refresh(accountId) {
    return this._instance(accountId).refresh();
  }

  async disconnect(accountId) {
    const id = this._accountId(accountId);
    const instance = this._instance(id);
    for (const [state, pending] of this.pendingOwners) {
      if (pending.accountId === id) this.pendingOwners.delete(state);
    }
    return instance.disconnect();
  }

  _prunePending(now = Date.now()) {
    for (const [state, pending] of this.pendingOwners) {
      if (now - pending.createdAt > 10 * 60 * 1000) this.pendingOwners.delete(state);
    }
  }
}

module.exports = { TikTokOAuthRegistry };
