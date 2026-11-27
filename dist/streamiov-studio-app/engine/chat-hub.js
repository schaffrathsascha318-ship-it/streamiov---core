'use strict';

const SOURCES = Object.freeze(['tiktok', 'twitch', 'discord', 'local_test']);
const SEND_TARGETS = Object.freeze(['tiktok', 'twitch']);
const MAX_MESSAGES = 1000;

class StreamiovChatHub {
  constructor() {
    this.messages = [];
    this.adapters = new Map();
    this.sequence = 0;
  }

  registerAdapter(platform, adapter) {
    if (!SEND_TARGETS.includes(platform)) throw new TypeError('Unbekannte Chat-Ausgabe.');
    if (!adapter || typeof adapter.sendMessage !== 'function') throw new TypeError('Chat-Adapter benötigt sendMessage().');
    this.adapters.set(platform, adapter);
    return () => this.adapters.delete(platform);
  }

  receive(message) {
    if (!message || !SOURCES.includes(message.source)) throw new TypeError('Ungültige Nachrichtenquelle.');
    const text = typeof message.text === 'string' ? message.text.trim() : '';
    if (!text || text.length > 2000) throw new TypeError('Nachricht muss 1–2000 Zeichen lang sein.');
    const createdAt = message.createdAt ? new Date(message.createdAt) : new Date();
    if (!Number.isFinite(createdAt.getTime())) throw new TypeError('Ungültiger Nachrichtenzeitpunkt.');
    const normalized = Object.freeze({
      id: String(message.id || 'local-' + (++this.sequence)).slice(0, 200),
      source: message.source,
      channel: String(message.channel || '').slice(0, 120),
      author: String(message.author || 'Unbekannt').slice(0, 120),
      text,
      createdAt: createdAt.toISOString(),
      receivedAt: new Date().toISOString(),
      kind: String(message.kind || 'message').slice(0, 40),
      roles: Array.isArray(message.roles) ? message.roles.slice(0, 10).map(role => String(role).slice(0, 40)) : [],
      badges: String(message.badges || '').slice(0, 400),
      platform_user_id: String(message.platform_user_id || '').slice(0, 80)
    });
    if (this.messages.some(item => item.source === normalized.source && item.id === normalized.id)) {
      return { accepted: false, duplicate: true, message: normalized };
    }
    this.messages.push(normalized);
    this.messages.sort((a, b) => Date.parse(a.createdAt) - Date.parse(b.createdAt) || a.receivedAt.localeCompare(b.receivedAt));
    if (this.messages.length > MAX_MESSAGES) this.messages.splice(0, this.messages.length - MAX_MESSAGES);
    return { accepted: true, duplicate: false, message: normalized };
  }

  list({ source = 'all', query = '', limit = 100 } = {}) {
    if (source !== 'all' && !SOURCES.includes(source)) throw new TypeError('Unbekannter Chat-Filter.');
    const needle = String(query).trim().toLocaleLowerCase();
    const safeLimit = Math.max(1, Math.min(500, Number.isInteger(limit) ? limit : 100));
    return this.messages.filter(item =>
      (source === 'all' || item.source === source) &&
      (!needle || [item.author, item.channel, item.text].some(value => value.toLocaleLowerCase().includes(needle)))
    ).slice(-safeLimit);
  }

  async send({ text, targets, permissions = {} } = {}) {
    const content = typeof text === 'string' ? text.trim() : '';
    if (!content || content.length > 2000) throw new TypeError('Nachricht muss 1–2000 Zeichen lang sein.');
    if (!Array.isArray(targets) || targets.length === 0 ||
        targets.some(target => !SEND_TARGETS.includes(target)) ||
        new Set(targets).size !== targets.length) {
      throw new TypeError('Sendeziele müssen ausdrücklich TikTok und/oder Twitch sein.');
    }
    const results = [];
    for (const platform of targets) {
      if (permissions[platform] !== true) {
        results.push({ platform, ok: false, error: 'Sende-Berechtigung für diese Plattform fehlt.' });
        continue;
      }
      const adapter = this.adapters.get(platform);
      if (!adapter) {
        results.push({ platform, ok: false, error: 'Offizieller Plattform-Chatadapter ist noch nicht verbunden.' });
        continue;
      }
      try {
        const result = await adapter.sendMessage(content);
        results.push({ platform, ok: result?.ok === true, error: result?.ok === true ? null : String(result?.error || 'Plattform hat die Nachricht nicht bestätigt.') });
      } catch (error) {
        results.push({ platform, ok: false, error: String(error?.message || 'Senden fehlgeschlagen.').slice(0, 300) });
      }
    }
    return { ok: results.length > 0 && results.every(result => result.ok), results };
  }

  snapshot() {
    return Object.freeze({
      supportedSources: SOURCES,
      outboundTargets: SEND_TARGETS,
      connectedAdapters: [...this.adapters.keys()],
      messageCount: this.messages.length,
      messages: this.list({ limit: 100 })
    });
  }
}

module.exports = { StreamiovChatHub, SOURCES, SEND_TARGETS };
