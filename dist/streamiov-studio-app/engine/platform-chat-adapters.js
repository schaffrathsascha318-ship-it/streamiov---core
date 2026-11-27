'use strict';

const { CHAT_SCOPES, IRC_READ_SCOPES, LEGACY_IRC_CHAT_SCOPES } = require('../twitch-oauth');

const TIKTOK_CHAT_STATUS = Object.freeze({
  platform: 'tiktok',
  supported: false,
  status: 'not_supported',
  sendable: false,
  error: 'TikTok-Chat-Versand ist offiziell nicht autorisiert oder technisch nicht unterstützt.',
  reauthorizationPrepared: false
});

function normalizeChatError(error) {
  const message = String(error?.message || error || '');
  if (error?.code === 'oauth_permission_required' || message.includes('OAuth-Berechtigung erforderlich')) return 'OAuth-Berechtigung erforderlich';
  if (message.includes('length_invalid')) return 'Twitch-Chat-Nachrichten dürfen 1–500 Zeichen lang sein.';
  if (message.includes('not_connected') || message.includes('validation_failed') || message.includes('client_mismatch')) return 'Verbindung getrennt';
  if (message.includes('refresh') || message.includes('expired')) return 'Token abgelaufen';
  return ('Twitch-Chat-Sende fehlgeschlagen: ' + (message || 'unbekannter Fehler')).slice(0, 300);
}

function twitchChatStatus(getOAuth) {
  let state;
  try { state = getOAuth().status(); }
  catch (error) {
    return {
      platform: 'twitch', supported: true, status: 'configuration_required', sendable: false,
      error: 'Twitch-OAuth ist nicht konfiguriert: ' + normalizeChatError(error),
      requiredScopes: [...CHAT_SCOPES], ircScopes: [...IRC_READ_SCOPES],
    ircGranted: [], ircReadable: false, legacyIrcScopes: [...LEGACY_IRC_CHAT_SCOPES]
    };
  }
  const base = {
    platform: 'twitch',
    supported: true,
    scopes: Array.isArray(state.scopes) ? [...state.scopes] : [],
    requiredScopes: [...(state.chatScopes?.requiredForHelix || CHAT_SCOPES)],
    ircScopes: [...IRC_READ_SCOPES],
    ircGranted: Array.isArray(state.chatScopes?.ircGranted) ? [...state.chatScopes.ircGranted] : [],
    ircReadable: IRC_READ_SCOPES.every(scope => (state.chatScopes?.ircGranted || []).includes(scope)),
    legacyIrcScopes: [...(state.chatScopes?.legacyIrcOnly || LEGACY_IRC_CHAT_SCOPES)],
    legacyIrcGranted: Array.isArray(state.chatScopes?.legacyGranted) ? [...state.chatScopes.legacyGranted] : [],
    refreshAvailable: Boolean(state.refreshAvailable)
  };
  if (state.status === 'not_connected') {
    return { ...base, status: 'disconnected', sendable: false, error: 'Verbindung getrennt' };
  }
  const chatGranted = Boolean(state.chatScopes?.sufficientForHelix);
  if (state.status === 'token_expired') {
    if (chatGranted && state.refreshAvailable) {
      return { ...base, status: 'refresh_required', sendable: true, error: 'Token abgelaufen; wird beim Senden erneuert.' };
    }
    return { ...base, status: chatGranted ? 'token_expired' : 'oauth_permission_required', sendable: false,
      error: chatGranted ? 'Token abgelaufen' : 'OAuth-Berechtigung erforderlich',
      oauthPermissionRequired: !chatGranted };
  }
  if (!chatGranted) {
    return { ...base, status: 'oauth_permission_required', sendable: false,
      error: 'OAuth-Berechtigung erforderlich', oauthPermissionRequired: true };
  }
  return { ...base, status: 'ready', sendable: true, error: null, oauthPermissionRequired: false };
}

function createTwitchChatAdapter({ getOAuth }) {
  if (typeof getOAuth !== 'function') throw new TypeError('getOAuth ist erforderlich.');
  return Object.freeze({
    platform: 'twitch',
    status: () => twitchChatStatus(getOAuth),
    sendMessage: async text => {
      try {
        const result = await getOAuth().sendChatMessage(text);
        return result?.ok === true && result?.isSent === true && typeof result.messageId === 'string'
          ? { ok: true, platform: 'twitch', messageId: result.messageId, isSent: true }
          : { ok: false, platform: 'twitch', error: 'Twitch hat die Nachricht nicht bestätigt.' };
      } catch (error) {
        return { ok: false, platform: 'twitch', error: normalizeChatError(error) };
      }
    }
  });
}

function platformChatStatuses({ getOAuth } = {}) {
  return Object.freeze({
    twitch: twitchChatStatus(typeof getOAuth === 'function' ? getOAuth : () => { throw new Error('twitch_not_configured'); }),
    tiktok: TIKTOK_CHAT_STATUS
  });
}

function resolveChatPermissions(statuses) {
  return Object.freeze({
    twitch: Boolean(statuses?.twitch?.sendable),
    tiktok: Boolean(statuses?.tiktok?.sendable)
  });
}

function connectedPlatformAdapters(statuses) {
  return Object.freeze(
    Object.keys(statuses || {}).filter(platform =>
      Object.hasOwn(statuses, platform) && statuses[platform]?.sendable === true)
  );
}

module.exports = {
  TIKTOK_CHAT_STATUS,
  normalizeChatError,
  twitchChatStatus,
  createTwitchChatAdapter,
  platformChatStatuses,
  resolveChatPermissions,
  connectedPlatformAdapters
};
