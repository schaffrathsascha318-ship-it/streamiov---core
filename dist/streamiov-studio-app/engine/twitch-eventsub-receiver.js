'use strict';

const EVENTSUB_URL = 'wss://eventsub.wss.twitch.tv/ws';
const TOKEN_URL = 'https://id.twitch.tv/oauth2/token';
const SUBSCRIPTIONS_URL = 'https://api.twitch.tv/helix/eventsub/subscriptions';
const RECONNECT_DELAYS_MS = Object.freeze([1000, 2000, 4000]);
const SUBSCRIPTIONS = Object.freeze([
  Object.freeze({ type: 'channel.cheer', version: '1', conditionKeys: ['broadcaster_user_id'], auth: 'app', scopes: [] }),
  Object.freeze({ type: 'channel.raid', version: '1', conditionKeys: ['to_broadcaster_user_id'], auth: 'app', scopes: [] }),
  Object.freeze({ type: 'channel.follow', version: '2', conditionKeys: ['broadcaster_user_id', 'moderator_user_id'], auth: 'user', scopes: ['moderator:read:followers'] }),
  Object.freeze({ type: 'channel.subscribe', version: '1', conditionKeys: ['broadcaster_user_id'], auth: 'user', scopes: ['channel:read:subscriptions'] }),
  Object.freeze({ type: 'channel.subscription.gift', version: '1', conditionKeys: ['broadcaster_user_id'], auth: 'user', scopes: ['channel:read:subscriptions'] })
]);

function normalizeNotification(message) {
  const metadata = message?.metadata;
  const event = message?.payload?.event || message?.event;
  if (!metadata || !event) return null;
  if (metadata.subscription_type === 'channel.cheer') {
    const bits = Number(event.bits);
    if (!Number.isFinite(bits) || bits <= 0) return null;
    return Object.freeze({
      source: 'twitch',
      kind: 'cheer',
      id: String(metadata.message_id || '').slice(0, 200),
      author: String(event.user_name || event.user_login || 'Twitch-Zuschauer').slice(0, 120),
      channel: '',
      text: 'Cheer: ' + Math.round(bits) + ' Bits' + (event.message ? ' · ' + String(event.message).slice(0, 300) : ''),
      createdAt: String(metadata.message_timestamp || new Date().toISOString()).slice(0, 40)
    });
  }
  if (metadata.subscription_type === 'channel.raid') {
    const viewers = Number(event.viewers);
    if (!Number.isFinite(viewers) || viewers <= 0) return null;
    return Object.freeze({
      source: 'twitch',
      kind: 'raid',
      id: String(metadata.message_id || '').slice(0, 200),
      author: String(event.from_broadcaster_user_name || event.from_broadcaster_user_login || 'Twitch-Raid').slice(0, 120),
      channel: '',
      text: 'Raid: ' + Math.round(viewers) + ' Zuschauer',
      createdAt: String(metadata.message_timestamp || new Date().toISOString()).slice(0, 40)
    });
  }
  const timestamp = String(metadata.message_timestamp || new Date().toISOString()).slice(0, 40);
  const id = String(metadata.message_id || '').slice(0, 200);
  if (metadata.subscription_type === 'channel.follow') {
    const author = String(event.user_name || event.user_login || 'Twitch-Follower').slice(0, 120);
    return Object.freeze({ source: 'twitch', kind: 'follow', id, author, channel: '', text: 'Follow: ' + author, createdAt: timestamp });
  }
  if (metadata.subscription_type === 'channel.subscribe') {
    const author = String(event.user_name || event.user_login || 'Twitch-Abonnent').slice(0, 120);
    const tier = String(event.tier || '').slice(0, 12);
    const gift = event.is_gift === true ? ' · Geschenk' : '';
    return Object.freeze({ source: 'twitch', kind: 'subscribe', id, author, channel: '', text: 'Sub: ' + author + (tier ? ' · Tier ' + tier : '') + gift, createdAt: timestamp });
  }
  if (metadata.subscription_type === 'channel.subscription.gift') {
    const total = Number(event.total);
    if (!Number.isFinite(total) || total <= 0) return null;
    const author = event.is_anonymous === true ? 'Anonym' : String(event.user_name || event.user_login || 'Twitch-Geber').slice(0, 120);
    return Object.freeze({ source: 'twitch', kind: 'gift_subscription', id, author, channel: '', text: 'Gift-Sub: ' + author + ' · ' + Math.round(total) + ' Subscription(s)', createdAt: timestamp });
  }
  return null;
}

class TwitchEventSubReceiver {
  constructor({ getOAuth, onEvent, onStatus } = {}) {
    if (typeof getOAuth !== 'function') throw new TypeError('getOAuth ist erforderlich.');
    if (typeof onEvent !== 'function') throw new TypeError('onEvent ist erforderlich.');
    this.getOAuth = getOAuth;
    this.onEvent = onEvent;
    this.onStatus = typeof onStatus === 'function' ? onStatus : () => {};
    this.socket = null;
    this.sessionId = null;
    this.stopped = false;
    this.manualStopped = false;
    this.retryIndex = 0;
    this.retryTimer = null;
    this.connected = false;
    this.lastError = null;
    this.activeSubscriptions = [];
    this.unavailableSubscriptions = [];
    this.WebSocketClass = globalThis.WebSocket;
  }

  status() {
    return Object.freeze({
      platform: 'twitch',
      transport: 'eventsub_websocket',
      state: this.connected ? 'connected' : this.socket ? 'connecting' : (this.stopped || this.manualStopped) ? 'stopped' : 'offline',
      sessionId: this.sessionId ? this.sessionId.slice(0, 80) : null,
      subscribed: [...this.activeSubscriptions],
      unavailable: [...this.unavailableSubscriptions],
      connected: this.connected,
      error: this.lastError
    });
  }

  _setStatus(connected, error = null) {
    this.connected = connected;
    this.lastError = error ? String(error).slice(0, 300) : null;
    this.onStatus(this.status());
  }

  async _appToken() {
    const oauth = this.getOAuth();
    const response = await oauth.fetch(TOKEN_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded', 'Cache-Control': 'no-store' },
      body: new URLSearchParams({
        client_id: oauth.clientId,
        client_secret: oauth.clientSecret,
        grant_type: 'client_credentials'
      }).toString()
    });
    const data = await response.json();
    if (!response.ok || typeof data?.access_token !== 'string' || !data.access_token) {
      throw new Error('twitch_app_token_unavailable');
    }
    return data.access_token;
  }

  async _subscribe(tokens, condition) {
    const oauth = this.getOAuth();
    const active = [];
    for (const subscription of SUBSCRIPTIONS) {
      const token = subscription.auth === 'app' ? tokens.appToken : tokens.userToken;
      if (!token) continue;
      const response = await oauth.fetch(SUBSCRIPTIONS_URL, {
        method: 'POST',
        headers: {
          Authorization: 'Bearer ' + token,
          'Client-Id': oauth.clientId,
          'Content-Type': 'application/json',
          'Cache-Control': 'no-store'
        },
        body: JSON.stringify({
          type: subscription.type,
          version: subscription.version,
          condition: Object.fromEntries(subscription.conditionKeys.map(key => [key, condition])),
          transport: { method: 'websocket', session_id: this.sessionId }
        })
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        if (response.status === 409) continue;
        throw new Error('eventsub_subscription_failed:' + subscription.type + ':' + String(payload?.message || response.status).slice(0, 120));
      }
      active.push(subscription.type);
    }
    this.activeSubscriptions = active;
  }

  async start() {
    if (this.stopped) throw new Error('twitch_eventsub_stopped');
    this.manualStopped = false;
    if (this.socket && (this.socket.readyState === 0 || this.socket.readyState === 1)) return this.status();
    if (typeof this.WebSocketClass !== 'function') throw new Error('websocket_unavailable');
    const oauth = this.getOAuth();
    const state = oauth.status();
    if (state.status === 'not_connected') throw new Error('twitch_account_not_connected');
    const users = await oauth.helix('/users');
    const broadcasterId = users?.data?.[0]?.id;
    if (typeof broadcasterId !== 'string' || !/^\d{1,20}$/.test(broadcasterId)) {
      throw new Error('twitch_broadcaster_identity_unavailable');
    }
    const granted = new Set(Array.isArray(state.scopes) ? state.scopes : []);
    const unavailable = SUBSCRIPTIONS
      .filter(subscription => subscription.auth === 'user' && !subscription.scopes.every(scope => granted.has(scope)))
      .map(subscription => subscription.type);
    this.unavailableSubscriptions = unavailable;
    const tokens = {
      appToken: SUBSCRIPTIONS.some(subscription => subscription.auth === 'app') ? await this._appToken() : null,
      userToken: SUBSCRIPTIONS.some(subscription => subscription.auth === 'user' && subscription.scopes.every(scope => granted.has(scope)))
        ? await oauth.accessToken() : null,
    };
    const socket = new this.WebSocketClass(EVENTSUB_URL);
    this.socket = socket;
    this._setStatus(false);
    socket.addEventListener('open', () => {
      if (this.socket !== socket || this.stopped) return;
      this.retryIndex = 0;
    });
    socket.addEventListener('message', event => {
      const raw = String(event.data || '');
      let message;
      try { message = JSON.parse(raw); } catch { return; }
      if (message?.metadata?.message_type === 'session_welcome') {
        const sessionId = message?.payload?.session?.id;
        if (typeof sessionId !== 'string' || !sessionId) return;
        this.sessionId = sessionId;
        void this._subscribe(tokens, broadcasterId).then(() => {
          this.retryIndex = 0;
          this._setStatus(true);
        }).catch(error => {
          this._setStatus(false, error.message);
          this.stop({ permanent: true });
        });
        return;
      }
      if (message?.metadata?.message_type === 'notification') {
        const normalized = normalizeNotification(message);
        if (normalized) this.onEvent(normalized);
        return;
      }
      if (message?.metadata?.message_type === 'session_revoke') {
        this.stop({ permanent: true });
        this._setStatus(false, 'Twitch-EventSub-Sitzung wurde widerrufen.');
      }
    });
    socket.addEventListener('error', () => {
      if (this.socket === socket) this._setStatus(false, 'Twitch-EventSub-Verbindung fehlgeschlagen.');
    });
    socket.addEventListener('close', () => {
      if (this.socket !== socket) return;
      this.socket = null;
      this.sessionId = null;
      this._setStatus(false);
      this._scheduleRetry();
    });
    return this.status();
  }

  stop({ permanent = false } = {}) {
    this.stopped = permanent;
    this.manualStopped = true;
    if (this.retryTimer) clearTimeout(this.retryTimer);
    this.retryTimer = null;
    const socket = this.socket;
    this.socket = null;
    this.sessionId = null;
    this.activeSubscriptions = [];
    this._setStatus(false);
    if (socket && socket.readyState <= 1) socket.close(1000, 'studio_stop');
  }

  _scheduleRetry() {
    if (this.stopped || this.retryTimer) return;
    if (this.retryIndex >= RECONNECT_DELAYS_MS.length) {
      this._setStatus(false, 'Twitch-EventSub-Wiederverbindung fehlgeschlagen.');
      return;
    }
    const delay = RECONNECT_DELAYS_MS[this.retryIndex++];
    this.retryTimer = setTimeout(() => {
      this.retryTimer = null;
      void this.start().catch(error => {
        this._setStatus(false, error.message);
        this._scheduleRetry();
      });
    }, delay);
  }
}

module.exports = {
  TwitchEventSubReceiver, EVENTSUB_URL, SUBSCRIPTIONS,
  normalizeNotification
};
