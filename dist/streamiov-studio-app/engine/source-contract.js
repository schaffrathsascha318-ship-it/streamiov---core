'use strict';

(function (root, factory) {
  if (typeof module === 'object' && module.exports) {
    module.exports = factory();
  } else {
    root.StreamiovSourceContract = factory();
  }
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  const CONTRACT_VERSION = 1;
  const SUPPORTED_TYPES = Object.freeze([
    'camera', 'screen', 'window', 'title', 'text', 'image', 'video', 'audio', 'color'
  ]);
  const LEGACY_TYPES = Object.freeze({ capture: 'screen' });
  const RUNTIME_TYPES = Object.freeze(['camera', 'screen', 'window', 'image', 'video', 'audio']);
  const CAPTURE_TYPES = Object.freeze(['camera', 'screen', 'window']);
  const MEDIA_TYPES = Object.freeze(['image', 'video', 'audio']);
  const STATUS = Object.freeze([
    'not-applicable', 'connecting', 'ready', 'stale',
    'permission-denied', 'device-busy', 'ended', 'error'
  ]);
  const STATUS_LABELS = Object.freeze({
    'not-applicable': 'kein Gerät nötig',
    connecting: 'verbinde',
    ready: 'bereit',
    stale: 'veraltet',
    'permission-denied': 'Zugriff verweigert',
    'device-busy': 'Gerät belegt',
    ended: 'beendet',
    error: 'Fehler'
  });

  const validId = value => typeof value === 'string' && /^[a-zA-Z0-9_-]{1,80}$/.test(value);
  const opaque = value => typeof value === 'string' && value.length > 0 && value.length <= 512 &&
    !/[\u0000-\u001f\u007f]/.test(value) ? value : null;

  function normalizeType(type) {
    return Object.prototype.hasOwnProperty.call(LEGACY_TYPES, type) ? LEGACY_TYPES[type] : type;
  }

  function descriptor(source) {
    if (!source || typeof source !== 'object' || Array.isArray(source)) return null;
    const type = normalizeType(source.type);
    if (!validId(source.id) || !SUPPORTED_TYPES.includes(type)) return null;
    const settings = source.settings && typeof source.settings === 'object' && !Array.isArray(source.settings)
      ? source.settings : {};
    const name = typeof source.name === 'string' && source.name.trim() ? source.name.trim().slice(0, 80) : type;
    const volume = Number.isFinite(source.volume) ? Math.max(0, Math.min(1, source.volume)) : 1;
    const result = {
      id: validId(source.id) ? source.id : null,
      type,
      name,
      enabled: source.enabled !== false,
      muted: source.muted === true,
      volume
    };
    if (type === 'camera') {
      result.deviceId = opaque(settings.deviceId);
      result.width = Number.isInteger(settings.width) ? settings.width : null;
      result.height = Number.isInteger(settings.height) ? settings.height : null;
      result.fps = Number.isInteger(settings.fps) ? settings.fps : null;
    } else if (type === 'screen' || type === 'window') {
      result.sourceId = opaque(settings.sourceId);
      result.displayId = opaque(settings.displayId);
    } else if (type === 'audio' && settings.deviceId) {
      result.deviceId = opaque(settings.deviceId);
    } else if (MEDIA_TYPES.includes(type)) {
      result.assetId = validId(settings.assetId) ? settings.assetId : null;
    }
    return result;
  }

  function needsRuntime(type) {
    return RUNTIME_TYPES.includes(normalizeType(type));
  }

  function classifyError(error) {
    const source = error && typeof error === 'object' ? error : { message: String(error || '') };
    const name = String(source.name || '');
    const message = String(source.message || source || '').toLowerCase();
    if (source.streamiovSourceStatus === 'stale') return 'stale';
    if (name === 'NotAllowedError' || name === 'PermissionDeniedError' ||
        name === 'SecurityError' || message.includes('zugriff verweigert')) return 'permission-denied';
    if (name === 'NotFoundError' || name === 'DevicesNotFoundError' ||
        name === 'OverconstrainedError' || message.includes('keine bildschirmquelle') ||
        message.includes('keine quelle gewählt') || message.includes('nicht mehr verfügbar')) return 'stale';
    if (name === 'NotReadableError' || name === 'TrackStartError' ||
        name === 'AbortError' || message.includes('belegt')) return 'device-busy';
    if (message.includes('beendet') || message.includes('ended')) return 'ended';
    return 'error';
  }

  function availabilitySnapshot(availability) {
    const source = availability && typeof availability === 'object' ? availability : {};
    const devices = Array.isArray(source.devices) ? source.devices : [];
    const displaySources = Array.isArray(source.displaySources) ? source.displaySources : [];
    const assets = Array.isArray(source.assets)
      ? source.assets.map(asset => typeof asset === 'string' ? asset : asset && asset.id).filter(Boolean)
      : [];
    return {
      devices: devices.filter(device => device && typeof device === 'object'),
      displaySources: displaySources.filter(item => item && typeof item === 'object'),
      assets,
      checked: Array.isArray(source.devices) || Array.isArray(source.displaySources) || Array.isArray(source.assets)
    };
  }

  function validateAvailability(source, availability) {
    const info = descriptor(source);
    if (!info) return { ok: false, status: 'error', availabilityChecked: false, findings: ['Ungültige Quelle.'] };
    if (!needsRuntime(info.type)) {
      return { ok: true, status: 'not-applicable', availabilityChecked: false, findings: [] };
    }
    const current = availabilitySnapshot(availability);
    const findings = [];
    if (info.type === 'camera') {
      const cameras = current.devices.filter(device => device.kind === 'videoinput');
      if (info.deviceId && current.checked && !cameras.some(device => device.deviceId === info.deviceId)) {
        findings.push('Gespeicherte Kamera ist nicht mehr verfügbar.');
      }
      if (!info.deviceId && current.checked && !cameras.length) {
        findings.push('Keine Kamera gefunden.');
      }
    } else if (info.type === 'audio' && info.deviceId) {
      const microphones = current.devices.filter(device => device.kind === 'audioinput');
      if (current.checked && !microphones.some(device => device.deviceId === info.deviceId)) {
        findings.push('Gespeichertes Mikrofon ist nicht mehr verfügbar.');
      }
    } else if (info.type === 'screen' || info.type === 'window') {
      const selector = info.sourceId || info.displayId;
      if (!selector) findings.push('Für diese Quelle ist keine Bildschirmfreigabe gewählt.');
      if (selector && current.checked && !current.displaySources.some(item =>
        item.id === selector || item.sourceId === selector ||
        (info.displayId && item.displayId === info.displayId))) {
        findings.push('Gespeicherte Bildschirmquelle ist nicht mehr verfügbar.');
      }
    } else if (MEDIA_TYPES.includes(info.type)) {
      if (!info.assetId) findings.push('Für diese Quelle ist keine Mediendatei gewählt.');
      if (info.assetId && current.checked && !current.assets.includes(info.assetId)) {
        findings.push('Gespeicherte Mediendatei ist nicht mehr verfügbar.');
      }
    }
    return {
      ok: findings.length === 0,
      status: findings.length ? 'stale' : 'ready',
      availabilityChecked: current.checked,
      findings
    };
  }

  function sourceHealth(source, runtime, availability) {
    const info = descriptor(source);
    if (!info) return { status: 'error', message: 'Ungültige Quelle.', findings: ['Ungültige Quelle.'] };
    const checked = validateAvailability(source, availability);
    if (!checked.ok) {
      return { status: 'stale', message: checked.findings.join(' '), findings: checked.findings };
    }
    if (!needsRuntime(info.type)) {
      return { status: 'not-applicable', message: '', findings: [] };
    }
    if (!runtime) return { status: 'connecting', message: '', findings: [] };
    if (runtime.error) {
      const status = classifyError(runtime.error);
      const message = String(runtime.error.message || runtime.error).slice(0, 220);
      return { status, message, findings: [message] };
    }
    if (runtime.stream && typeof runtime.stream.getTracks === 'function') {
      const tracks = runtime.stream.getTracks();
      if (!tracks.some(track => track.readyState === 'live')) {
        return { status: 'ended', message: 'Die Quelle wurde beendet.', findings: ['Die Quelle wurde beendet.'] };
      }
    }
    if (runtime.element && runtime.element.error) {
      const message = String(runtime.element.error.message || runtime.element.error).slice(0, 220);
      return { status: 'error', message, findings: [message] };
    }
    return { status: 'ready', message: '', findings: [] };
  }

  function healthLabel(status) {
    return STATUS_LABELS[status] || String(status || 'error');
  }

  return {
    CONTRACT_VERSION,
    SUPPORTED_TYPES,
    CAPTURE_TYPES,
    MEDIA_TYPES,
    RUNTIME_TYPES,
    STATUS,
    normalizeType,
    descriptor,
    sourceDescriptor: descriptor,
    needsRuntime,
    classifyError,
    availabilitySnapshot,
    validateAvailability,
    sourceHealth,
    healthLabel
  };
});
