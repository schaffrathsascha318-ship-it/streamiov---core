'use strict';

const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');

const AUTH_URL = 'https://id.twitch.tv/oauth2/authorize';
const TOKEN_URL = 'https://id.twitch.tv/oauth2/token';
const VALIDATE_URL = 'https://id.twitch.tv/oauth2/validate';
const HELIX = 'https://api.twitch.tv/helix';
const REQUIRED_SCOPES = Object.freeze(['channel:read:stream_key']);
const CHAT_SCOPES = Object.freeze(['user:write:chat']);
const IRC_READ_SCOPES = Object.freeze(['chat:read']);
const EVENT_SCOPES = Object.freeze(['channel:read:subscriptions', 'moderator:read:followers']);
const LEGACY_IRC_CHAT_SCOPES = Object.freeze(['chat:edit']);
const MAX_CHAT_MESSAGE_LENGTH = 500;

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
    this.refreshInFlight = null;
    this.store = options.store || new TwitchTokenStore({
      filePath: options.tokenFile || path.join(process.cwd(), 'data', 'oauth', 'twitch.json'),
      key: options.encryptionKey || env.STREAMIOV_TWITCH_TOKEN_ENCRYPTION_KEY
    });
  }
  createAuthorizationUrl({ chat = false, events = false } = {}) {
    const state = crypto.randomBytes(32).toString('base64url');
    const scopes = [...new Set([...REQUIRED_SCOPES, ...(chat ? [...CHAT_SCOPES, ...IRC_READ_SCOPES] : []), ...(events ? EVENT_SCOPES : [])])];
    this.pending.set(state, { created: this.clock(), chat, events });
    const url = new URL(AUTH_URL);
    url.search = new URLSearchParams({
      client_id: this.clientId, redirect_uri: this.redirectUri, response_type: 'code',
      scope: scopes.join(' '), state, force_verify: 'false'
    }).toString();
    return { url: url.toString(), state, scopes, purpose: events ? 'chat_and_event_authorization' : chat ? 'chat_authorization' : 'connection', expiresInSeconds: 600 };
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
    const pending = this.pending.get(state);
    this.pending.delete(state);
    if (!pending || this.clock() - pending.created > 600000) throw new Error('twitch_oauth_state_invalid_or_expired');
    if (typeof code !== 'string' || !code || code.length > 2048) throw new Error('twitch_authorization_code_invalid');
    const tokens = await this.requestToken({ code, grant_type: 'authorization_code', redirect_uri: this.redirectUri });
    const granted = Array.isArray(tokens.scope) ? tokens.scope : [];
    if (!REQUIRED_SCOPES.every(scope => granted.includes(scope))) throw new Error('twitch_required_scope_not_granted');
    if (pending.chat && ![...CHAT_SCOPES, ...IRC_READ_SCOPES].every(scope => granted.includes(scope))) {
      return Object.freeze({ ok: false, status: 'oauth_permission_required', error: 'OAuth-Berechtigung erforderlich', chatScopeGranted: false });
    }
    this.store.save({
      accessToken: tokens.access_token, refreshToken: tokens.refresh_token,
      expiresAt: this.clock() + Number(tokens.expires_in || 0) * 1000,
      scopes: granted
    });
    return { ok: true, ...this.status() };
  }
  async accessToken() {
    if (this.refreshInFlight) return this.refreshInFlight;
    const tokens = this.store.load();
    if (!tokens) throw new Error('twitch_account_not_connected');
    if (tokens.expiresAt > this.clock() + 60000) return tokens.accessToken;
    if (!tokens.refreshToken) throw new Error('twitch_refresh_token_unavailable');

    const expectedRefreshToken = tokens.refreshToken;
    this.refreshInFlight = (async () => {
      const current = this.store.load();
      if (!current) throw new Error('twitch_account_not_connected');
      if (current.refreshToken !== expectedRefreshToken || current.expiresAt > this.clock() + 60000) {
        return current.accessToken;
      }
      const next = await this.requestToken({ grant_type: 'refresh_token', refresh_token: expectedRefreshToken });
      if (!next.refresh_token) throw new Error('twitch_refresh_token_rotation_missing');
      const rotated = {
        accessToken: next.access_token,
        refreshToken: next.refresh_token,
        expiresAt: this.clock() + Number(next.expires_in || 0) * 1000,
        scopes: Array.isArray(next.scope) ? next.scope : current.scopes
      };
      if (!REQUIRED_SCOPES.every(scope => rotated.scopes.includes(scope))) throw new Error('twitch_required_scope_not_granted');
      const latest = this.store.load();
      if (latest && latest.refreshToken !== expectedRefreshToken) return latest.accessToken;
      this.store.save(rotated);
      return rotated.accessToken;
    })();
    try {
      return await this.refreshInFlight;
    } finally {
      this.refreshInFlight = null;
    }
  }
  async validate() {
    const token = await this.accessToken();
    const response = await this.fetch(VALIDATE_URL, {
      headers: { Authorization: 'Bearer ' + token, 'Cache-Control': 'no-store' }
    });
    let data;
    try { data = await response.json(); }
    catch { throw new Error('twitch_token_validation_invalid_response'); }
    if (!response.ok || typeof data?.client_id !== 'string' || !data.client_id) throw new Error('twitch_token_validation_failed');
    if (data.client_id !== this.clientId) throw new Error('twitch_token_client_mismatch');
    return {
      clientId: data.client_id,
      login: typeof data.login === 'string' ? data.login : null,
      userId: typeof data.user_id === 'string' ? data.user_id : null,
      scopes: Array.isArray(data.scopes) ? data.scopes : [],
      expiresIn: Number(data.expires_in) || 0
    };
  }
  async sendChatMessage(text) {
    const message = typeof text === 'string' ? text.trim() : '';
    if (!message || message.length > MAX_CHAT_MESSAGE_LENGTH) throw new Error('twitch_chat_message_length_invalid');
    const identity = await this.validate();
    if (!CHAT_SCOPES.every(scope => identity.scopes.includes(scope))) {
      const error = new Error('OAuth-Berechtigung erforderlich');
      error.code = 'oauth_permission_required';
      throw error;
    }
    if (!identity.userId) throw new Error('twitch_chat_identity_unavailable');
    const endpoint = new URL('/helix/chat/messages', HELIX);
    endpoint.searchParams.set('broadcaster_id', identity.userId);
    endpoint.searchParams.set('sender_id', identity.userId);
    const response = await this.fetch(endpoint.toString(), {
      method: 'POST',
      headers: {
        Authorization: 'Bearer ' + await this.accessToken(),
        'Client-Id': this.clientId,
        'Content-Type': 'application/json',
        'Cache-Control': 'no-store'
      },
      body: JSON.stringify({ message })
    });
    let payload;
    try { payload = await response.json(); }
    catch { throw new Error('twitch_chat_send_invalid_response'); }
    if (!response.ok) {
      const error = new Error('Twitch hat die Nachricht nicht bestätigt (HTTP ' + response.status + ').');
      error.status = response.status;
      error.code = response.status === 401 || response.status === 403 ? 'oauth_permission_required' : 'twitch_chat_send_failed';
      throw error;
    }
    const sent = Array.isArray(payload?.data)
      ? payload.data.find(item => item?.is_sent === true && typeof item.message_id === 'string' && item.message_id)
      : null;
    if (!sent) {
      const reason = Array.isArray(payload?.data) && payload.data[0]?.drop_reason?.code
        ? ' (' + String(payload.data[0].drop_reason.code).slice(0, 80) + ')'
        : '';
      throw new Error('Twitch hat die Nachricht nicht gesendet' + reason + '.');
    }
    return Object.freeze({ platform: 'twitch', ok: true, messageId: sent.message_id, isSent: true });
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
  async getLiveStatus() {
    const users = await this.helix('/users');
    const broadcasterId = users.data?.[0]?.id;
    if (!broadcasterId) throw new Error('twitch_broadcaster_identity_unavailable');
    const result = await this.helix('/streams?broadcaster_id=' + encodeURIComponent(broadcasterId));
    const stream = result.data?.[0];
    const live = Boolean(stream && stream.type === 'live' && typeof stream.id === 'string' && stream.id.trim());
    return Object.freeze({
      platform: 'twitch',
      live,
      confirmationId: live ? stream.id.trim().slice(0, 200) : null,
      title: live && typeof stream.title === 'string' ? stream.title.slice(0, 200) : null,
      viewerCount: live && Number.isFinite(Number(stream.viewer_count)) ? Number(stream.viewer_count) : null
    });
  }
  status() {
    const tokens = this.store.load();
    const chatScopes = {
      requiredForHelix: [...CHAT_SCOPES],
      legacyIrcOnly: [...LEGACY_IRC_CHAT_SCOPES],
      granted: CHAT_SCOPES.filter(scope => tokens?.scopes?.includes(scope)),
      legacyGranted: LEGACY_IRC_CHAT_SCOPES.filter(scope => tokens?.scopes?.includes(scope)),
      ircGranted: IRC_READ_SCOPES.filter(scope => tokens?.scopes?.includes(scope)),
      sufficientForHelix: Boolean(tokens && CHAT_SCOPES.every(scope => tokens.scopes?.includes(scope))),
      sufficientForIrc: Boolean(tokens && IRC_READ_SCOPES.every(scope => tokens.scopes?.includes(scope)))
    };
    const eventScopes = {
      required: [...EVENT_SCOPES],
      granted: EVENT_SCOPES.filter(scope => tokens?.scopes?.includes(scope)),
      subscriptions: EVENT_SCOPES.every(scope => tokens?.scopes?.includes(scope)),
      followers: Boolean(tokens?.scopes?.includes('moderator:read:followers'))
    };
    if (!tokens) return { status: 'not_connected', requiredScopes: [...REQUIRED_SCOPES], chatScopes, eventScopes, refreshAvailable: false, redirectUri: this.redirectUri };
    return { status: tokens.expiresAt <= this.clock() ? 'token_expired' : 'connected',
      scopes: [...(tokens.scopes || [])], streamKeyPermission: REQUIRED_SCOPES.every(scope => tokens.scopes?.includes(scope)),
      chatScopes, eventScopes, refreshAvailable: Boolean(tokens.refreshToken), redirectUri: this.redirectUri };
  }
  async disconnect() {
    const tokens = this.store.load();
    let revoked = true;
    let revokeError = null;
    if (tokens?.accessToken) {
      try {
        const response = await this.fetch('https://id.twitch.tv/oauth2/revoke', {
          method: 'POST', headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
          body: new URLSearchParams({ client_id: this.clientId, token: tokens.accessToken }).toString()
        });
        if (!response.ok) { revoked = false; revokeError = 'twitch_token_revoke_failed'; }
      } catch {
        revoked = false; revokeError = 'twitch_token_revoke_failed';
      }
    }
    this.store.clear(); this.pending.clear();
    return { status: 'disconnected', revoked, ...(revokeError ? { revokeError } : {}) };
  }
}
module.exports = {
  TwitchOAuth, TwitchTokenStore, REQUIRED_SCOPES, CHAT_SCOPES, IRC_READ_SCOPES,
  EVENT_SCOPES, LEGACY_IRC_CHAT_SCOPES, MAX_CHAT_MESSAGE_LENGTH, safeRedirect
};
