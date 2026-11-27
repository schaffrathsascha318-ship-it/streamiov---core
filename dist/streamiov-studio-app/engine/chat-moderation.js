'use strict';

const fs = require('node:fs');
const path = require('node:path');

const ROLES = Object.freeze(['viewer', 'subscriber', 'vip', 'moderator', 'broadcaster']);
const ACTIONS = Object.freeze(['send', 'speak']);
const MAX_WORDS = 200;
const MAX_USERS = 200;
const CONTROL_PATTERN = /[\u0000-\u001f\u007f]/g;
const DEFAULT_PERMISSIONS = Object.freeze({
  viewer: Object.freeze({ send: true, speak: false }),
  subscriber: Object.freeze({ send: true, speak: true }),
  vip: Object.freeze({ send: true, speak: true }),
  moderator: Object.freeze({ send: true, speak: true }),
  broadcaster: Object.freeze({ send: true, speak: true }),
});

function cleanText(value, maxLength) {
  return String(value || '').replace(CONTROL_PATTERN, '').trim().slice(0, maxLength);
}

function identityFor(source, author) {
  return cleanText(source, 40).toLocaleLowerCase() + ':' + cleanText(author, 120).toLocaleLowerCase();
}

class ChatModeration {
  constructor({ filePath, now = Date.now } = {}) {
    if (typeof filePath !== 'string' || !filePath) throw new TypeError('Moderationspfad ist erforderlich.');
    this.filePath = path.resolve(filePath);
    this.now = typeof now === 'function' ? now : Date.now;
    this.blockedWords = [];
    this.bannedUsers = [];
    this.slowModeSeconds = 0;
    this.permissions = Object.fromEntries(ROLES.map(role => [role, { ...DEFAULT_PERMISSIONS[role] }]));
    this.lastMessageAt = new Map();
    this._load();
  }

  _load() {
    try {
      const raw = JSON.parse(fs.readFileSync(this.filePath, 'utf8'));
      if (Array.isArray(raw.blockedWords)) this.blockedWords = raw.blockedWords.map(value => cleanText(value, 120)).filter(Boolean).slice(0, MAX_WORDS);
      if (Array.isArray(raw.bannedUsers)) this.bannedUsers = raw.bannedUsers.map(value => cleanText(value, 200)).filter(Boolean).slice(0, MAX_USERS);
      if (Number.isFinite(raw.slowModeSeconds)) this.slowModeSeconds = Math.max(0, Math.min(3600, Math.round(raw.slowModeSeconds)));
      for (const role of ROLES) {
        for (const action of ACTIONS) {
          if (typeof raw.permissions?.[role]?.[action] === 'boolean') this.permissions[role][action] = raw.permissions[role][action];
        }
      }
    } catch {}
  }

  _persist() {
    fs.mkdirSync(path.dirname(this.filePath), { recursive: true, mode: 0o700 });
    const temp = this.filePath + '.' + process.pid + '.tmp';
    fs.writeFileSync(temp, JSON.stringify({
      blockedWords: this.blockedWords,
      bannedUsers: this.bannedUsers,
      slowModeSeconds: this.slowModeSeconds,
      permissions: this.permissions,
    }), { flag: 'wx', mode: 0o600 });
    fs.renameSync(temp, this.filePath);
    try { fs.chmodSync(this.filePath, 0o600); } catch {}
  }

  snapshot() {
    return Object.freeze({
      blockedWords: Object.freeze([...this.blockedWords]),
      bannedUsers: Object.freeze([...this.bannedUsers]),
      slowModeSeconds: this.slowModeSeconds,
      permissions: Object.freeze(Object.fromEntries(ROLES.map(role => [role, Object.freeze({ ...this.permissions[role] })]))),
      roles: ROLES,
      actions: ACTIONS,
    });
  }

  setBlockedWords(values) {
    if (!Array.isArray(values)) throw new TypeError('Wortfilter muss eine Liste sein.');
    this.blockedWords = [...new Set(values.map(value => cleanText(value, 120).toLocaleLowerCase()).filter(Boolean))].slice(0, MAX_WORDS);
    this._persist();
    return this.snapshot();
  }

  setBannedUsers(values) {
    if (!Array.isArray(values)) throw new TypeError('Sperrliste muss eine Liste sein.');
    this.bannedUsers = [...new Set(values.map(value => cleanText(value, 200).toLocaleLowerCase()).filter(Boolean))].slice(0, MAX_USERS);
    this._persist();
    return this.snapshot();
  }

  setSlowMode(seconds) {
    const value = Number(seconds);
    if (!Number.isFinite(value)) throw new TypeError('Slow-Mode muss eine Zahl sein.');
    this.slowModeSeconds = Math.max(0, Math.min(3600, Math.round(value)));
    this.lastMessageAt.clear();
    this._persist();
    return this.snapshot();
  }

  setRolePermissions(values) {
    if (!values || typeof values !== 'object') throw new TypeError('Rechtematrix ist ungültig.');
    for (const role of ROLES) {
      for (const action of ACTIONS) {
        const value = values[role]?.[action];
        if (typeof value === 'boolean') this.permissions[role][action] = value;
      }
    }
    this._persist();
    return this.snapshot();
  }

  ban({ source = 'twitch', author } = {}) {
    const identity = identityFor(source, author);
    if (!identity.split(':')[1]) throw new TypeError('Ein Benutzername ist erforderlich.');
    if (!this.bannedUsers.includes(identity)) this.bannedUsers.push(identity);
    this._persist();
    return this.snapshot();
  }

  unban({ source = 'twitch', author } = {}) {
    const identity = identityFor(source, author);
    this.bannedUsers = this.bannedUsers.filter(item => item !== identity && item !== cleanText(author, 120).toLocaleLowerCase());
    this._persist();
    return this.snapshot();
  }

  rolesFor(message) {
    const badges = String(message?.badges || '').toLocaleLowerCase();
    const roles = Array.isArray(message?.roles) ? message.roles.map(role => cleanText(role, 40).toLocaleLowerCase()) : [];
    const result = new Set();
    for (const role of roles) if (ROLES.includes(role) && role !== 'viewer') result.add(role);
    if (badges.includes('broadcaster/')) result.add('broadcaster');
    if (badges.includes('subscriber/') || badges.includes('founder/')) result.add('subscriber');
    if (badges.includes('vip/')) result.add('vip');
    if (badges.includes('moderator/')) result.add('moderator');
    if (!result.size) result.add('viewer');
    return [...ROLES.filter(role => result.has(role))];
  }

  can(role, action) {
    if (!ROLES.includes(role) || !ACTIONS.includes(action)) return false;
    return this.permissions[role][action] === true;
  }

  evaluate(message) {
    const source = cleanText(message?.source, 40);
    const author = cleanText(message?.author, 120);
    const text = cleanText(message?.text, 2000).toLocaleLowerCase();
    const identity = identityFor(source, author);
    if (this.bannedUsers.includes(identity) || this.bannedUsers.includes(author.toLocaleLowerCase())) {
      return Object.freeze({ allowed: false, reason: 'banned_user', roles: this.rolesFor(message) });
    }
    const word = this.blockedWords.find(item => item && text.includes(item));
    if (word) return Object.freeze({ allowed: false, reason: 'blocked_word', word, roles: this.rolesFor(message) });
    const now = this.now();
    const last = this.lastMessageAt.get(identity);
    if (this.slowModeSeconds > 0 && last !== undefined && now - last < this.slowModeSeconds * 1000) {
      return Object.freeze({ allowed: false, reason: 'slow_mode', roles: this.rolesFor(message) });
    }
    this.lastMessageAt.set(identity, now);
    return Object.freeze({ allowed: true, reason: null, roles: this.rolesFor(message) });
  }
}

module.exports = { ChatModeration, ROLES, ACTIONS, DEFAULT_PERMISSIONS };
