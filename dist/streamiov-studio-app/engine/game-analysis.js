'use strict';

const fs = require('node:fs');
const path = require('node:path');
const { randomUUID } = require('node:crypto');
const vision = require('./gameplay-vision');
const gameAI = require('./game-ai');

const KINDS = Object.freeze([
  'gameplay', 'score', 'kill', 'objective', 'combo', 'reward', 'death', 'defeat', 'victory',
]);
const HIGHLIGHT_KINDS = Object.freeze(['score', 'kill', 'objective', 'combo', 'reward', 'victory']);
const MAX_GAMES = 24;
const MAX_ENTRIES = 120;
const MAX_TITLE = 120;
const MAX_DETAIL = 240;
const MAX_REPLAY_FRAMES = 24;
const CONTROL_PATTERN = /[\u0000-\u001f\u007f]/g;

function clean(value, maxLength) {
  return String(value ?? '').replace(CONTROL_PATTERN, '').trim().slice(0, maxLength);
}

function safeNumber(value, fallback = 0) {
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
}

function newProfile() {
  return {
    notes: '',
    goals: [],
    tags: [],
    preferredSource: 'program',
    visionSensitivity: 70,
    updatedAt: null,
  };
}

function newGame(id, title, source, processName) {
  return {
    id,
    title,
    source,
    processName,
    status: 'NEEDS_REVIEW',
    detection: 'process_list',
    session: { active: false, startedAt: null, endedAt: null },
    stats: {
      observations: 0,
      score: 0,
      kills: 0,
      objectives: 0,
      combos: 0,
      rewards: 0,
      deaths: 0,
      defeats: 0,
      victories: 0,
      seconds: 0,
      frameAnalyses: 0,
      reactionTotal: 0,
      reactionCount: 0,
    },
    highlights: [],
    replayMarkers: [],
    advice: [],
    situations: [],
    sessions: [],
    replays: [],
    profile: newProfile(),
    progress: { level: 1, xp: 0, totalXp: 0 },
    autoDetectedAt: null,
    lastObservedAt: null,
  };
}

class GameAnalysis {
  constructor({ filePath, now = Date.now } = {}) {
    if (typeof filePath !== 'string' || !filePath) throw new TypeError('Analysepfad ist erforderlich.');
    this.filePath = path.resolve(filePath);
    this.now = typeof now === 'function' ? now : Date.now;
    this.games = new Map();
    this.autoDetection = { enabled: false, intervalMs: 10000 };
    this._frames = new Map();
    this._load();
  }

  _load() {
    try {
      const raw = JSON.parse(fs.readFileSync(this.filePath, 'utf8'));
      if (raw.autoDetection?.enabled === true) this.autoDetection.enabled = true;
      const interval = Math.round(Number(raw.autoDetection?.intervalMs));
      if (Number.isFinite(interval)) this.autoDetection.intervalMs = Math.max(3000, Math.min(60000, interval));
      if (!Array.isArray(raw?.games)) return;
      for (const entry of raw.games.slice(0, MAX_GAMES)) {
        const id = clean(entry?.id, 80);
        if (!/^[a-z0-9-]{2,64}$/.test(id)) continue;
        const game = newGame(id, clean(entry.title, MAX_TITLE) || id,
          entry.source === 'streamiov' ? 'streamiov' : 'external', clean(entry.processName, MAX_TITLE));
        game.status = entry.status === 'ANALYZING' ? 'ANALYZING' : 'NEEDS_REVIEW';
        game.detection = clean(entry.detection, 40) || 'process_list';
        game.session.active = entry.session?.active === true;
        game.session.startedAt = Number.isFinite(entry.session?.startedAt) ? entry.session.startedAt : null;
        game.session.endedAt = Number.isFinite(entry.session?.endedAt) ? entry.session.endedAt : null;
        for (const key of Object.keys(game.stats)) {
          const value = safeNumber(entry.stats?.[key]);
          if (Number.isFinite(value)) game.stats[key] = Math.max(0, Math.round(value));
        }
        game.highlights = this._copyEntries(entry.highlights, 60);
        game.replayMarkers = this._copyEntries(entry.replayMarkers, 100);
        game.advice = this._copyEntries(entry.advice, 30);
        game.situations = this._copySituations(entry.situations);
        game.sessions = this._copySessions(entry.sessions);
        game.replays = this._copyReplays(entry.replays);
        game.profile = this._copyProfile(entry.profile);
        game.progress.level = Math.max(1, Math.round(safeNumber(entry.progress?.level, 1)));
        game.progress.xp = Math.max(0, Math.round(safeNumber(entry.progress?.xp)));
        game.progress.totalXp = Math.max(0, Math.round(safeNumber(entry.progress?.totalXp)));
        game.autoDetectedAt = Number.isFinite(entry.autoDetectedAt) ? entry.autoDetectedAt : null;
        game.lastObservedAt = Number.isFinite(entry.lastObservedAt) ? entry.lastObservedAt : null;
        this.games.set(id, game);
      }
    } catch {}
  }

  _copyEntries(values, limit) {
    if (!Array.isArray(values)) return [];
    return values.slice(-limit).map(entry => Object.freeze({
      id: clean(entry?.id, 80),
      at: safeNumber(entry?.at),
      kind: clean(entry?.kind, 40),
      label: clean(entry?.label, MAX_TITLE),
      detail: clean(entry?.detail, MAX_DETAIL),
      source: clean(entry?.source, 40) || 'manual',
    }));
  }

  _copySituations(values) {
    if (!Array.isArray(values)) return [];
    return values.slice(-120).map(entry => Object.freeze({
      id: clean(entry?.id, 80),
      at: safeNumber(entry?.at),
      situation: clean(entry?.situation, 60),
      confidence: Math.max(0, Math.min(1, safeNumber(entry?.confidence, 0.5))),
      signals: Array.isArray(entry?.signals) ? entry.signals.slice(0, 8).map(signal => clean(signal, 40)) : [],
      score: Math.max(0, Math.min(100, Math.round(safeNumber(entry?.score)))),
      source: clean(entry?.source, 40) || 'frame',
    }));
  }

  _copySessions(values) {
    if (!Array.isArray(values)) return [];
    return values.slice(-60).map(entry => Object.freeze({
      startedAt: safeNumber(entry?.startedAt),
      endedAt: safeNumber(entry?.endedAt),
      seconds: Math.max(0, Math.round(safeNumber(entry?.seconds))),
      observations: Math.max(0, Math.round(safeNumber(entry?.observations))),
      highlights: Math.max(0, Math.round(safeNumber(entry?.highlights))),
    }));
  }

  _copyReplays(values) {
    if (!Array.isArray(values)) return [];
    return values.slice(-12).map(entry => Object.freeze({
      id: clean(entry?.id, 80),
      at: safeNumber(entry?.at),
      name: clean(entry?.name, MAX_TITLE),
      durationMs: Math.max(0, Math.round(safeNumber(entry?.durationMs))),
      sizeBytes: Math.max(0, Math.round(safeNumber(entry?.sizeBytes))),
      frames: Math.max(0, Math.round(safeNumber(entry?.frames))),
      markers: Math.max(0, Math.round(safeNumber(entry?.markers))),
      averageLuminance: safeNumber(entry?.averageLuminance),
      averageMotion: safeNumber(entry?.averageMotion),
      situations: Array.isArray(entry?.situations)
        ? entry.situations.slice(0, 12).map(item => clean(item, 60)) : [],
      summary: clean(entry?.summary, MAX_DETAIL),
    }));
  }

  _copyProfile(value) {
    const profile = newProfile();
    profile.notes = clean(value?.notes, 4000);
    profile.goals = Array.isArray(value?.goals)
      ? value.goals.slice(0, 12).map(goal => clean(goal, MAX_TITLE)).filter(Boolean) : [];
    profile.tags = Array.isArray(value?.tags)
      ? value.tags.slice(0, 12).map(tag => clean(tag, 40)).filter(Boolean) : [];
    profile.preferredSource = value?.preferredSource === 'preview' ? 'preview' : 'program';
    const sensitivity = Math.round(safeNumber(value?.visionSensitivity, 70));
    profile.visionSensitivity = Math.max(40, Math.min(95, sensitivity));
    profile.updatedAt = Number.isFinite(value?.updatedAt) ? value.updatedAt : null;
    return profile;
  }

  _persist() {
    fs.mkdirSync(path.dirname(this.filePath), { recursive: true, mode: 0o700 });
    const temporary = this.filePath + '.' + process.pid + '.' + randomUUID() + '.tmp';
    fs.writeFileSync(temporary, JSON.stringify({
      schemaVersion: 2,
      autoDetection: this.autoDetection,
      games: [...this.games.values()],
    }), { flag: 'wx', mode: 0o600 });
    fs.renameSync(temporary, this.filePath);
    try { fs.chmodSync(this.filePath, 0o600); } catch {}
  }

  _game(id) {
    const game = this.games.get(clean(id, 80));
    if (!game) throw new Error('Spiel ist nicht als Analyseziel registriert.');
    return game;
  }

  _append(entries, entry, limit) {
    entries.push(Object.freeze(entry));
    if (entries.length > limit) entries.splice(0, entries.length - limit);
  }

  _id(item) {
    const explicit = clean(item?.id, 80);
    if (/^[a-z0-9-]{2,64}$/.test(explicit)) return explicit;
    const name = clean(item?.processName || item?.windowTitle, MAX_TITLE)
      .toLocaleLowerCase().replace(/\.(exe|app|bin)$/, '').replace(/[^a-z0-9]+/g, '-')
      .replace(/^-+|-+$/g, '').slice(0, 64);
    return name && name.length >= 2 ? name : 'unknown-game';
  }

  _addProgress(game, amount) {
    const gain = Math.max(0, Math.round(amount));
    game.progress.xp += gain;
    game.progress.totalXp += gain;
    while (game.progress.xp >= game.progress.level * 100) {
      game.progress.xp -= game.progress.level * 100;
      game.progress.level += 1;
    }
  }

  _markHighlight(game, { at, kind, detail, source = 'manual', score = 0 }) {
    const highlight = {
      id: 'highlight-' + at.toString(36) + '-' + game.highlights.length.toString(36),
      at, kind, label: kind, detail: clean(detail, MAX_DETAIL), source,
    };
    const marker = {
      id: 'replay-' + at.toString(36) + '-' + game.replayMarkers.length.toString(36),
      at, kind, label: clean(detail, MAX_TITLE) || kind,
      detail: clean(detail, MAX_DETAIL), source,
    };
    this._append(game.highlights, highlight, 60);
    this._append(game.replayMarkers, marker, 100);
    this._addProgress(game, 10 + Math.round(score / 10));
    return { highlight, marker };
  }

  snapshot() {
    return Object.freeze({
      schemaVersion: 2,
      kinds: KINDS,
      autoDetection: Object.freeze({ ...this.autoDetection }),
      games: Object.freeze([...this.games.values()].map(game => Object.freeze({
        id: game.id,
        title: game.title,
        source: game.source,
        processName: game.processName,
        status: game.status,
        detection: game.detection,
        session: Object.freeze({ ...game.session }),
        stats: Object.freeze({ ...game.stats }),
        highlights: Object.freeze(game.highlights.map(item => ({ ...item }))),
        replayMarkers: Object.freeze(game.replayMarkers.map(item => ({ ...item }))),
        advice: Object.freeze(game.advice.map(item => ({ ...item }))),
        situations: Object.freeze(game.situations.map(item => ({ ...item }))),
        sessions: Object.freeze(game.sessions.map(item => ({ ...item }))),
        replays: Object.freeze(game.replays.map(item => ({ ...item }))),
        profile: Object.freeze({ ...game.profile, goals: Object.freeze([...game.profile.goals]), tags: Object.freeze([...game.profile.tags]) }),
        progress: Object.freeze({ ...game.progress }),
        autoDetectedAt: game.autoDetectedAt,
        lastObservedAt: game.lastObservedAt,
      }))),
    });
  }

  setAutoDetection(payload = {}) {
    if (payload.enabled !== undefined && typeof payload.enabled !== 'boolean') {
      throw new TypeError('Automatische Erkennung muss aktiviert oder deaktiviert sein.');
    }
    if (payload.enabled !== undefined) this.autoDetection.enabled = payload.enabled;
    if (payload.intervalMs !== undefined) {
      const interval = Math.round(Number(payload.intervalMs));
      if (!Number.isFinite(interval)) throw new TypeError('Das Erkennungsintervall muss eine Zahl sein.');
      this.autoDetection.intervalMs = Math.max(3000, Math.min(60000, interval));
    }
    this._persist();
    return this.snapshot();
  }

  detect(games, options = {}) {
    if (!Array.isArray(games)) throw new TypeError('Prozessliste muss eine Liste sein.');
    const automatic = options.automatic === true;
    const detected = [];
    for (const item of games) {
      if (this.games.size >= MAX_GAMES && !this.games.has(this._id(item))) break;
      const confidence = typeof item.confidenceScore === 'number'
        ? item.confidenceScore
        : item.confidence === 'possible' ? 0.68 : 0.12;
      if (automatic && (item.likelyGame === false || confidence < 0.25)) continue;
      const id = this._id(item);
      const title = clean(item.title || item.windowTitle, MAX_TITLE) || clean(item.processName, MAX_TITLE);
      if (!title) continue;
      const source = item.source === 'streamiov' || item.streamiovGame === true ? 'streamiov' :
        /streamiov/i.test(String(item.processName || '') + ' ' + title) ? 'streamiov' : 'external';
      const game = this.games.get(id) || newGame(id, title, source, clean(item.processName, MAX_TITLE));
      game.title = title;
      game.source = source;
      game.processName = clean(item.processName, MAX_TITLE);
      game.detection = automatic ? 'process_list_auto' : clean(item.detection, 40) || 'process_list';
      game.status = game.session.active ? 'ANALYZING' : 'NEEDS_REVIEW';
      game.autoDetectedAt = automatic ? this.now() : null;
      game.lastObservedAt = this.now();
      this.games.set(id, game);
      detected.push(game.id);
    }
    this._persist();
    return this.snapshot();
  }

  startSession(id) {
    const game = this._game(id);
    game.session = { active: true, startedAt: this.now(), endedAt: null };
    game.status = 'ANALYZING';
    this._persist();
    return this.snapshot();
  }

  stopSession(id) {
    const game = this._game(id);
    const endedAt = this.now();
    const seconds = Number.isFinite(game.session.startedAt)
      ? Math.max(0, Math.round((endedAt - game.session.startedAt) / 1000)) : 0;
    game.stats.seconds += seconds;
    if (Number.isFinite(game.session.startedAt)) {
      this._append(game.sessions, {
        startedAt: game.session.startedAt,
        endedAt,
        seconds,
        observations: game.stats.observations,
        highlights: game.highlights.length,
      }, 60);
    }
    game.session = { active: false, startedAt: game.session.startedAt, endedAt };
    game.status = 'NEEDS_REVIEW';
    this._persist();
    return this.snapshot();
  }

  observe(payload = {}) {
    const game = this._game(payload.id);
    const kind = clean(payload.kind, 40);
    if (!KINDS.includes(kind)) throw new Error('Unbekannte Gameplay-Beobachtung.');
    const now = this.now();
    const detail = clean(payload.detail, MAX_DETAIL);
    const score = Math.max(0, Math.min(1000000, Math.round(safeNumber(payload.score))));
    const reactionMs = Math.max(0, Math.min(60000, Math.round(safeNumber(payload.reactionMs))));
    game.stats.observations += 1;
    game.stats.score += kind === 'score' ? score : 0;
    game.stats.kills += kind === 'kill' ? 1 : 0;
    game.stats.objectives += kind === 'objective' ? 1 : 0;
    game.stats.combos += kind === 'combo' ? 1 : 0;
    game.stats.rewards += kind === 'reward' ? 1 : 0;
    game.stats.deaths += kind === 'death' ? 1 : 0;
    game.stats.defeats += kind === 'defeat' ? 1 : 0;
    game.stats.victories += kind === 'victory' ? 1 : 0;
    if (reactionMs > 0) {
      game.stats.reactionTotal += reactionMs;
      game.stats.reactionCount += 1;
    }
    game.lastObservedAt = now;
    this._addProgress(game, kind === 'victory' ? 20 : 2);
    const result = { kind, id: game.id, title: game.title, detail, score, at: now, highlight: false };
    if (HIGHLIGHT_KINDS.includes(kind)) {
      const marked = this._markHighlight(game, { at: now, kind, detail });
      result.highlight = true;
      result.highlightId = marked.highlight.id;
      result.replayMarkerId = marked.marker.id;
    }
    this._persist();
    return { ok: true, observation: Object.freeze(result), snapshot: this.snapshot() };
  }

  frame(payload = {}) {
    const game = this._game(payload.id);
    const analysed = vision.analyseFrame(payload);
    const previous = this._frames.get(game.id);
    const diff = vision.compareFrames(analysed, previous);
    this._frames.set(game.id, analysed.frame);
    const classification = vision.classify(analysed, diff);
    const score = vision.highlightScore(analysed, diff, classification);
    const now = this.now();
    const entry = {
      id: 'situation-' + now.toString(36) + '-' + game.situations.length.toString(36),
      at: now,
      situation: classification.situation,
      confidence: classification.confidence,
      signals: classification.signals,
      score,
      source: clean(payload.source, 40) || game.profile.preferredSource,
    };
    this._append(game.situations, entry, 120);
    game.stats.frameAnalyses += 1;
    game.stats.observations += 1;
    game.lastObservedAt = now;
    this._addProgress(game, 1);
    let highlight = null;
    const threshold = game.profile.visionSensitivity;
    if (score >= threshold && diff.available && diff.changedRatio > 0.08) {
      highlight = this._markHighlight(game, {
        at: now,
        kind: classification.situation === 'gefahr' ? 'death' : 'gameplay',
        detail: `${classification.situation} · Frame-Score ${score}`,
        source: 'vision',
        score,
      });
    }
    this._persist();
    return Object.freeze({
      ok: true,
      analysis: Object.freeze({
        width: analysed.width,
        height: analysed.height,
        meanLuminance: analysed.meanLuminance,
        luminanceDeviation: analysed.luminanceDeviation,
        edgeDensity: analysed.edgeDensity,
        darkRatio: analysed.darkRatio,
        redRatio: analysed.redRatio,
        greenRatio: analysed.greenRatio,
        situation: classification.situation,
        confidence: classification.confidence,
        signals: Object.freeze(classification.signals),
        diff: Object.freeze({ ...diff }),
        score,
      }),
      situation: Object.freeze({ ...entry }),
      highlight: highlight ? Object.freeze({ id: highlight.highlight.id, label: highlight.highlight.label, markerId: highlight.marker.id }) : null,
      snapshot: this.snapshot(),
    });
  }

  situations(id) {
    const game = this._game(id);
    return Object.freeze({
      ok: true,
      game: game.id,
      situations: Object.freeze(game.situations.map(entry => ({ ...entry }))),
    });
  }

  stats(id) {
    const games = id ? [this._game(id)] : [...this.games.values()];
    const counts = {};
    let observationCount = 0;
    let highlightCount = 0;
    let frameCount = 0;
    let wins = 0;
    let losses = 0;
    let reactionTotal = 0;
    let reactionCount = 0;
    let longestSessionMs = 0;
    let sessionCount = 0;
    let scoreTotal = 0;
    for (const game of games) {
      observationCount += game.stats.observations;
      highlightCount += game.highlights.length;
      frameCount += game.stats.frameAnalyses;
      wins += game.stats.victories;
      losses += game.stats.defeats + game.stats.deaths;
      reactionTotal += game.stats.reactionTotal;
      reactionCount += game.stats.reactionCount;
      scoreTotal += game.stats.score;
      sessionCount += game.sessions.length + (game.session.active ? 1 : 0);
      for (const session of game.sessions) longestSessionMs = Math.max(longestSessionMs, session.seconds * 1000);
      for (const entry of game.situations) counts[entry.situation] = (counts[entry.situation] || 0) + 1;
    }
    return Object.freeze({
      ok: true,
      game: id ? games[0].id : null,
      sessionCount,
      observationCount,
      highlightCount,
      frameCount,
      wins,
      losses,
      averageReactionMs: reactionCount > 0 ? reactionTotal / reactionCount : 0,
      averageScore: observationCount > 0 ? scoreTotal / observationCount : 0,
      longestSessionMs,
      situationCounts: Object.freeze(counts),
      progress: Object.freeze(id ? { ...games[0].progress } : { level: 1, xp: 0, totalXp: 0 }),
    });
  }

  strategy(id) {
    const game = this._game(id);
    const stats = this.stats(id);
    const recommendations = gameAI.recommendations({
      stats: { ...stats, strategy: [] },
      situations: game.situations,
      profile: game.profile,
    });
    const entry = Object.freeze({
      id: 'strategy-' + this.now().toString(36) + '-' + game.advice.length.toString(36),
      at: this.now(),
      kind: 'strategy',
      label: 'Gaming-KI',
      detail: recommendations.slice(0, 3).map(item => `${item.title}: ${item.detail}`).join(' '),
      source: 'local_ai',
    });
    this._append(game.advice, entry, 30);
    this._persist();
    return Object.freeze({
      ok: true,
      recommendations: Object.freeze(recommendations.map(item => Object.freeze(item))),
      advice: entry,
      snapshot: this.snapshot(),
    });
  }

  assistant(id) {
    const game = this._game(id);
    const stats = game.stats;
    const lines = [];
    if (stats.observations < 3) lines.push('Zu wenige Beobachtungen; Analyse bleibt NEEDS_REVIEW.');
    if (stats.deaths > stats.victories) lines.push('Tode überwiegen: Positionen und Rückzugswege zuerst prüfen.');
    if (stats.combos >= 3) lines.push('Combo-Rate ist hoch: erfolgreiche Rotation beibehalten.');
    if (stats.objectives === 0 && stats.kills > 2) lines.push('Kills dominieren: Zielobjekte aktiv mitzählen.');
    if (stats.rewards === 0 && stats.observations >= 5) lines.push('Belohnungen fehlen: Reward-Ereignisse manuell bestätigen.');
    if (!lines.length) lines.push('Keine Auffälligkeit aus den lokalen Beobachtungen ableitbar.');
    const recommendations = gameAI.recommendations({
      stats: { ...this.stats(id), strategy: [] },
      situations: game.situations,
      profile: game.profile,
    });
    if (recommendations.length) lines.push(`Empfehlung: ${recommendations[0].title}. ${recommendations[0].detail}`);
    const entry = Object.freeze({
      id: 'advice-' + this.now().toString(36) + '-' + game.advice.length.toString(36),
      at: this.now(),
      kind: 'assistant',
      label: 'Lokaler Gaming-Assistent',
      detail: lines.join(' '),
    });
    this._append(game.advice, entry, 30);
    this._persist();
    return { ok: true, advice: entry, snapshot: this.snapshot() };
  }

  profile(id, payload = {}) {
    const game = this._game(id);
    const current = game.profile;
    const next = this._copyProfile({
      ...current,
      notes: payload.notes !== undefined ? clean(payload.notes, 4000) : current.notes,
      goals: payload.goals !== undefined ? payload.goals : current.goals,
      tags: payload.tags !== undefined ? payload.tags : current.tags,
      preferredSource: payload.preferredSource !== undefined ? payload.preferredSource : current.preferredSource,
      visionSensitivity: payload.visionSensitivity !== undefined ? payload.visionSensitivity : current.visionSensitivity,
      updatedAt: this.now(),
    });
    game.profile = next;
    this._persist();
    return Object.freeze({ ok: true, profile: Object.freeze({ ...next, goals: Object.freeze([...next.goals]), tags: Object.freeze([...next.tags]) }), snapshot: this.snapshot() });
  }

  voice(id, text) {
    const game = this._game(id);
    const command = gameAI.voiceCommand(text);
    if (!command.ok) return Object.freeze({ ok: false, error: command.error });
    let speak = command.reply;
    if (command.intent === 'highlight') {
      const latest = game.situations[game.situations.length - 1];
      const marked = this._markHighlight(game, {
        at: this.now(),
        kind: latest?.situation === 'gefahr' ? 'death' : 'gameplay',
        detail: latest ? `Sprachmarkierung: ${latest.situation}` : 'Sprachmarkierung ohne Bildsituation',
        source: 'voice',
        score: latest?.score || 0,
      });
      speak += ` Marker ${marked.marker.id}.`;
    } else if (command.intent === 'stats') {
      speak = gameAI.summariseStats(this.stats(id));
    } else if (command.intent === 'strategy') {
      const recommendations = gameAI.recommendations({
        stats: { ...this.stats(id), strategy: [] },
        situations: game.situations,
        profile: game.profile,
      });
      speak = recommendations.length ? `${recommendations[0].title}. ${recommendations[0].detail}` : 'Keine Empfehlung verfügbar.';
    } else if (command.intent === 'note') {
      const notes = [game.profile.notes, command.data.text].filter(Boolean).join(' · ').slice(0, 4000);
      game.profile = this._copyProfile({ ...game.profile, notes, updatedAt: this.now() });
      speak = 'Notiz gespeichert.';
    } else if (command.intent === 'goal') {
      const goals = [...game.profile.goals, command.data.text].slice(-12);
      game.profile = this._copyProfile({ ...game.profile, goals, updatedAt: this.now() });
      speak = 'Ziel gespeichert.';
    } else if (command.intent === 'report') {
      const stats = this.stats(id);
      const recommendations = gameAI.recommendations({ stats: { ...stats, strategy: [] }, situations: game.situations, profile: game.profile });
      speak = `${gameAI.summariseStats(stats)} ${recommendations[0]?.title || 'Keine Auffälligkeit'}.`;
    }
    const entry = Object.freeze({
      id: 'voice-' + this.now().toString(36) + '-' + game.advice.length.toString(36),
      at: this.now(),
      kind: 'voice',
      label: 'Sprachbefehl',
      detail: clean(speak, MAX_DETAIL),
      source: 'voice',
    });
    this._append(game.advice, entry, 30);
    this._persist();
    return Object.freeze({ ok: true, intent: command.intent, reply: speak, advice: entry, snapshot: this.snapshot() });
  }

  replayImport(payload = {}) {
    const game = this._game(payload.id);
    const frames = Array.isArray(payload.frames) ? payload.frames.slice(0, MAX_REPLAY_FRAMES) : [];
    if (!frames.length) throw new TypeError('Replay enthält keine auswertbaren Bilder.');
    const now = this.now();
    const situationCounts = {};
    let previous = null;
    let luminanceTotal = 0;
    let motionTotal = 0;
    let markers = 0;
    for (const framePayload of frames) {
      const analysed = vision.analyseFrame(framePayload);
      const diff = vision.compareFrames(analysed, previous);
      previous = analysed.frame;
      const classification = vision.classify(analysed, diff);
      const score = vision.highlightScore(analysed, diff, classification);
      luminanceTotal += analysed.meanLuminance;
      motionTotal += diff.meanDelta;
      situationCounts[classification.situation] = (situationCounts[classification.situation] || 0) + 1;
      if (score >= game.profile.visionSensitivity && diff.changedRatio > 0.08) {
        const at = now + Math.round(safeNumber(framePayload.atMs));
        this._markHighlight(game, {
          at,
          kind: classification.situation === 'gefahr' ? 'death' : 'gameplay',
          detail: `Replay ${clean(payload.name, MAX_TITLE) || 'Aufnahme'} · ${classification.situation} · Score ${score}`,
          source: 'replay',
          score,
        });
        markers += 1;
      }
    }
    const situations = Object.keys(situationCounts).sort((a, b) => situationCounts[b] - situationCounts[a]).slice(0, 12);
    const analysis = Object.freeze({
      id: 'replay-analysis-' + now.toString(36) + '-' + game.replays.length.toString(36),
      at: now,
      name: clean(payload.name, MAX_TITLE) || 'Replay',
      durationMs: Math.max(0, Math.round(safeNumber(payload.durationMs))),
      sizeBytes: Math.max(0, Math.round(safeNumber(payload.sizeBytes))),
      frames: frames.length,
      markers,
      averageLuminance: Number((luminanceTotal / frames.length).toFixed(2)),
      averageMotion: Number((motionTotal / frames.length).toFixed(2)),
      situations: Object.freeze(situations),
      summary: `${frames.length} Frames, ${markers} Highlights, Situationen: ${situations.join(', ') || 'keine'}.`,
    });
    this._append(game.replays, analysis, 12);
    this._addProgress(game, markers * 10 + 5);
    this._persist();
    return Object.freeze({ ok: true, analysis, snapshot: this.snapshot() });
  }

  replay(id) {
    const game = this._game(id);
    return Object.freeze({
      ok: true,
      game: game.id,
      markers: Object.freeze(game.replayMarkers.map(marker => ({ ...marker }))),
      highlights: Object.freeze(game.highlights.map(highlight => ({ ...highlight }))),
      analyses: Object.freeze(game.replays.map(entry => ({ ...entry }))),
    });
  }
}

module.exports = { GameAnalysis, KINDS, HIGHLIGHT_KINDS };
