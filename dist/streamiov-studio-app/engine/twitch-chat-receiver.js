'use strict';

const IRC_URL = 'wss://irc-ws.chat.twitch.tv:443';
const REQUIRED_READ_SCOPE = 'chat:read';
const RECONNECT_DELAYS_MS = Object.freeze([1000, 2000, 4000]);

function parseTags(raw) {
  const tags = new Map();
  for (const part of String(raw || '').split(';')) {
    if (!part) continue;
    const index = part.indexOf('=');
    if (index < 0) continue;
    tags.set(part.slice(0, index), part.slice(index + 1));
  }
  return tags;
}

function decodeTag(value) {
  return String(value || '')
    .replace(/\\s/g, ' ')
    .replace(/\\:/g, ';')
    .replace(/\\\\/g, '\\')
    .replace(/\\r/g, '')
    .replace(/\\n/g, '');
}

function parsePrivmsg(line) {
  const match = /^(?:@([^ ]+) )?:([^!]+)!([^@]+)@([^ ]+) PRIVMSG (#[^ ]+) :(.*)$/.exec(line);
  if (!match) return null;
  const tags = parseTags(match[1]);
  const text = match[6];
  if (!text || text.length > 2000) return null;
  const messageId = decodeTag(tags.get('id')) || '';
  const timestamp = Number(tags.get('tmi-sent-ts'));
  const createdAt = Number.isFinite(timestamp) && timestamp > 0
    ? new Date(timestamp).toISOString()
    : new Date().toISOString();
  if (!Number.isFinite(Date.parse(createdAt))) return null;
  const badges = decodeTag(tags.get('badges'));
  const roles = [];
  if (/(^|,)broadcaster\//.test(badges)) roles.push('broadcaster');
  if (/(^|,)subscriber\//.test(badges) || /(^|,)founder\//.test(badges)) roles.push('subscriber');
  if (/(^|,)vip\//.test(badges)) roles.push('vip');
  if (/(^|,)moderator\//.test(badges)) roles.push('moderator');
  return Object.freeze({
    source: 'twitch',
    channel: match[5].slice(0, 121),
    author: decodeTag(tags.get('display-name')) || match[2].slice(0, 120),
    text,
    id: messageId.slice(0, 200) || 'twitch-' + Buffer.from(match[2] + text + createdAt).toString('hex').slice(0, 32),
    createdAt,
    kind: 'chat',
    badges: badges.slice(0, 400),
    roles,
    platform_user_id: decodeTag(tags.get('user-id')).slice(0, 80)
  });
}

class TwitchChatReceiver {
  constructor({ getOAuth, onMessage, onStatus } = {}) {
    if (typeof getOAuth !== 'function') throw new TypeError('getOAuth ist erforderlich.');
    if (typeof onMessage !== 'function') throw new TypeError('onMessage ist erforderlich.');
    this.getOAuth = getOAuth;
    this.onMessage = onMessage;
    this.onStatus = typeof onStatus === 'function' ? onStatus : () => {};
    this.socket = null;
    this.nick = null;
    this.stopped = false;
    this.manualStopped = false;
    this.retryIndex = 0;
    this.retryTimer = null;
    this.connected = false;
    this.lastError = null;
    this.WebSocketClass = globalThis.WebSocket;
  }

  status() {
    return Object.freeze({
      platform: 'twitch',
      state: this.connected ? 'connected' : this.socket ? 'connecting' : (this.stopped || this.manualStopped) ? 'stopped' : 'offline',
      nick: this.nick,
      connected: this.connected,
      error: this.lastError
    });
  }

  _setStatus(connected, error = null) {
    this.connected = connected;
    this.lastError = error ? String(error).slice(0, 300) : null;
    this.onStatus(this.status());
  }

  async start() {
    if (this.stopped) throw new Error('twitch_chat_receiver_stopped');
    this.manualStopped = false;
    if (this.socket && (this.socket.readyState === 0 || this.socket.readyState === 1)) return this.status();
    if (typeof this.WebSocketClass !== 'function') throw new Error('websocket_unavailable');
    const oauth = this.getOAuth();
    const state = oauth.status();
    if (state.status === 'not_connected') throw new Error('twitch_account_not_connected');
    const granted = Array.isArray(state.chatScopes?.ircGranted) ? state.chatScopes.ircGranted : [];
    if (!granted.includes(REQUIRED_READ_SCOPE)) throw new Error('oauth_permission_required');
    const token = await oauth.accessToken();
    if (typeof token !== 'string' || !token) throw new Error('twitch_access_token_unavailable');
    const users = await oauth.helix('/users');
    const login = users?.data?.[0]?.login;
    if (typeof login !== 'string' || !/^[a-zA-Z0-9_]{1,25}$/.test(login)) throw new Error('twitch_broadcaster_identity_unavailable');
    this.nick = login.toLowerCase();
    const socket = new this.WebSocketClass(IRC_URL);
    this.socket = socket;
    this._setStatus(false);
    socket.addEventListener('open', () => {
      if (this.socket !== socket || this.stopped) return;
      socket.send('CAP REQ :twitch.tv/tags twitch.tv/commands');
      socket.send('PASS oauth:' + token);
      socket.send('NICK ' + this.nick);
    });
    socket.addEventListener('message', event => this._onData(String(event.data || '')));
    socket.addEventListener('error', () => {
      if (this.socket === socket) this._setStatus(false, 'Twitch-Chat-Verbindung fehlgeschlagen.');
    });
    socket.addEventListener('close', () => {
      if (this.socket !== socket) return;
      this.socket = null;
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
    this._setStatus(false);
    if (socket && socket.readyState <= 1) socket.close(1000, 'studio_stop');
  }

  _scheduleRetry() {
    if (this.stopped || this.retryTimer) return;
    if (this.retryIndex >= RECONNECT_DELAYS_MS.length) {
      this._setStatus(false, 'Twitch-Chat-Wiederverbindung fehlgeschlagen.');
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

  _onData(data) {
    for (const line of data.split(/\r?\n/)) {
      if (!line) continue;
      if (/^PING(?: :.+)?$/.test(line)) {
        if (this.socket && this.socket.readyState === 1) this.socket.send('PONG :tmi.twitch.tv');
        continue;
      }
      if (line.includes('PRIVMSG')) {
        const message = parsePrivmsg(line);
        if (message) {
          this.retryIndex = 0;
          this.onMessage(message);
        }
        continue;
      }
      if (line.includes(' 001 ')) {
        this.retryIndex = 0;
        this._setStatus(true);
      }
      if (line.includes(' NOTICE ') && /authentication failed|Login unsuccessful/i.test(line)) {
        this.stop({ permanent: true });
        this._setStatus(false, 'Twitch-Chat-Anmeldung abgelehnt.');
      }
    }
  }
}

module.exports = { TwitchChatReceiver, IRC_URL, REQUIRED_READ_SCOPE, parsePrivmsg };
