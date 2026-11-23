'use strict';

const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');

const AUTH_URL = 'https://id.twitch.tv/oauth2/authorize';
const TOKEN_URL = 'https://id.twitch.tv/oauth2/token';
const VALIDATE_URL = 'https://id.twitch.tv/oauth2/validate';
const HELIX = 'https://api.twitch.tv/helix';
const REQUIRED_SCOPES = Object.freeze(['channel:read:stream_key']);

function required(value, name) {
  if (typeof value !== 'string' || !value.trim()) throw new Error(name + '_required');
  return value.trim();
}
function encryptionKey(value) {
  const key = Buffer.from(required(value, 'token_encryption_key'), 'base64');
  if (key.length !== 32) throw new Error('token_encryption_key_must_be_32_bytes');
  return key;
}
function safeRedirect(value) {
  const uri = new URL(required(value, 'redirect_uri'));
  if (uri.protocol !== 'http:' || uri.hostname !== '127.0.0.1' || !uri.port ||
      uri.pathname !== '/callback' || uri.search || uri.hash || uri.username || uri.password) {
    throw new Error('twitch_redirect_must_be_loopback_callback');
  }
  return uri.toString();
}
class TwitchTokenStore {
  constructor({ filePath, key }) { this.filePath = path.resolve(required(filePath, 'token_store_path')); this.key = encryptionKey(key); }
  save(value) {
    const iv = crypto.randomBytes(12);
    const cipher = crypto.createCipheriv('aes-256-gcm', this.key, iv);
    cipher.setAAD(Buffer.from('streamiov-twitch:oauth'));
    const ciphertext = Buffer.concat([cipher.update(JSON.stringify(value)), cipher.final()]);
    const record = { version: 1, iv: iv.toString('base64'), tag: cipher.getAuthTag().toString('base64'), ciphertext: ciphertext.toString('base64') };
    fs.mkdirSync(path.dirname(this.filePath), { recursive: true, mode: 0o700 });
    const temp = this.filePath + '.' + crypto.randomBytes(6).toString('hex') + '.tmp';
    fs.writeFileSync(temp, JSON.stringify(record), { flag: 'wx', mode: 0o600 });
    fs.renameSync(temp, this.filePath);
    try { fs.chmodSync(this.filePath, 0o600); } catch {}
  }
  load() {
    if (!fs.existsSync(this.filePath)) return null;
    const record = JSON.parse(fs.readFileSync(this.filePath, 'utf8'));
    if (record.version !== 1) throw new Error('twitch_token_record_invalid');
    const decipher = crypto.createDecipheriv('aes-256-gcm', this.key, Buffer.from(record.iv, 'base64'));
    decipher.setAAD(Buffer.from('streamiov-twitch:oauth'));
    decipher.setAuthTag(Buffer.from(record.tag, 'base64'));
    return JSON.parse(Buffer.concat([decipher.update(Buffer.from(record.ciphertext, 'base64')), decipher.final()]).toString('utf8'));
  }
  clear() { try { fs.unlinkSync(this.filePath); } catch (error) { if (error.code !== 'ENOENT') throw error; } }
}
class TwitchOAuth {
  constructor(options = {}) {
    const env = options.env || process.env;
    this.clientId = required(options.clientId || env.STREAMIOV_TWITCH_CLIENT_ID, 'twitch_client_id');
    this.clientSecret = required(options.clientSecret || env.STREAMIOV_TWITCH_CLIENT_SECRET, 'twitch_client_secret');
    this.redirectUri = safeRedirect(options.redirectUri || env.STREAMIOV_TWITCH_REDIRECT_URI || 'http://127.0.0.1:43821/callback');
    this.fetch = options.fetch || globalThis.fetch;
    this.clock = options.clock || Date.now;
    this.pending = new Map();
    this.store = options.store || new TwitchTokenStore({
      filePath: options.tokenFile || path.join(process.cwd(), 'data', 'oauth', 'twitch.json'),
      key: options.encryptionKey || env.STREAMIOV_TWITCH_TOKEN_ENCRYPTION_KEY
    });
  }
  createAuthorizationUrl() {
    const state = crypto.randomBytes(32).toString('base64url');
    this.pending.set(state, this.clock());
    const url = new URL(AUTH_URL);
    url.search = new URLSearchParams({
      client_id: this.clientId, redirect_uri: this.redirectUri, response_type: 'code',
      scope: REQUIRED_SCOPES.join(' '), state, force_verify: 'false'
    }).toString();
    return { url: url.toString(), state, expiresInSeconds: 600 };
  }
  async requestToken(fields) {
    const response = await this.fetch(TOKEN_URL, {
      method: 'POST', headers: { 'Content-Type': 'application/x-www-form-urlencoded', 'Cache-Control': 'no-store' },
      body: new URLSearchParams({ client_id: this.clientId, client_secret: this.clientSecret, ...fields }).toString()
    });
    const data = await response.json();
    if (!response.ok || data.status) throw new Error('twitch_token_request_failed');
    return data;
  }
  async callback({ code, state, error } = {}) {
    if (error) throw new Error('twitch_authorization_denied');
    const created = this.pending.get(state);
    this.pending.delete(state);
    if (!created || this.clock() - created > 600000) throw new Error('twitch_oauth_state_invalid_or_expired');
    if (typeof code !== 'string' || !code || code.length > 2048) throw new Error('twitch_authorization_code_invalid');
    const tokens = await this.requestToken({ code, grant_type: 'authorization_code', redirect_uri: this.redirectUri });
    const granted = Array.isArray(tokens.scope) ? tokens.scope : [];
    if (!REQUIRED_SCOPES.every(scope => granted.includes(scope))) throw new Error('twitch_required_scope_not_granted');
    this.store.save({
      accessToken: tokens.access_token, refreshToken: tokens.refresh_token,
      expiresAt: this.clock() + Number(tokens.expires_in || 0) * 1000,
      scopes: granted
    });
    return this.status();
  }
  async accessToken() {
    let tokens = this.store.load();
    if (!tokens) throw new Error('twitch_account_not_connected');
    if (tokens.expiresAt <= this.clock() + 60000) {
      if (!tokens.refreshToken) throw new Error('twitch_refresh_token_unavailable');
      const next = await this.requestToken({ grant_type: 'refresh_token', refresh_token: tokens.refreshToken });
      if (!next.refresh_token) throw new Error('twitch_refresh_token_rotation_missing');
      tokens = { accessToken: next.access_token, refreshToken: next.refresh_token,
        expiresAt: this.clock() + Number(next.expires_in || 0) * 1000,
        scopes: Array.isArray(next.scope) ? next.scope : tokens.scopes };
      if (!REQUIRED_SCOPES.every(scope => tokens.scopes.includes(scope))) throw new Error('twitch_required_scope_not_granted');
      this.store.save(tokens);
    }
    return tokens.accessToken;
  }
  async helix(pathname) {
    const token = await this.accessToken();
    const response = await this.fetch(HELIX + pathname, {
      headers: { Authorization: 'Bearer ' + token, 'Client-Id': this.clientId, 'Cache-Control': 'no-store' }
    });
    const data = await response.json();
    if (!response.ok) {
      const message = response.status === 403 ? 'twitch_stream_key_access_denied' : 'twitch_helix_request_failed';
      throw new Error(message);
    }
    return data;
  }
  async getStreamCredentials() {
    const users = await this.helix('/users');
    const broadcasterId = users.data?.[0]?.id;
    if (!broadcasterId) throw new Error('twitch_broadcaster_identity_unavailable');
    const result = await this.helix('/streams/key?broadcaster_id=' + encodeURIComponent(broadcasterId));
    const streamKey = result.data?.[0]?.stream_key;
    if (typeof streamKey !== 'string' || !streamKey) throw new Error('twitch_stream_key_unavailable');
    // Key is returned only to the trusted main-process stream launcher and is never persisted or logged.
    return Object.freeze({ platform: 'twitch', ingestUrl: 'rtmps://live.twitch.tv:443/app', streamKey });
  }
  status() {
    const tokens = this.store.load();
    if (!tokens) return { status: 'not_connected', requiredScopes: [...REQUIRED_SCOPES], redirectUri: this.redirectUri };
    return { status: tokens.expiresAt <= this.clock() ? 'token_expired' : 'connected',
      scopes: [...(tokens.scopes || [])], streamKeyPermission: REQUIRED_SCOPES.every(scope => tokens.scopes?.includes(scope)), redirectUri: this.redirectUri };
  }
  async disconnect() {
    const tokens = this.store.load();
    if (tokens?.accessToken) {
      const response = await this.fetch('https://id.twitch.tv/oauth2/revoke', {
        method: 'POST', headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: new URLSearchParams({ client_id: this.clientId, token: tokens.accessToken }).toString()
      });
      if (!response.ok) throw new Error('twitch_token_revoke_failed');
    }
    this.store.clear(); this.pending.clear();
    return { status: 'disconnected' };
  }
}
module.exports = { TwitchOAuth, TwitchTokenStore, REQUIRED_SCOPES, safeRedirect };
