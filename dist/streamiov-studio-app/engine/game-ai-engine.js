'use strict';

const { buildSpecialistDirectory } = require('./ai-work-orchestrator');

const AGENTS = Object.freeze([
  { id: 'game-analyzer', name: 'Game Analyzer', purpose: 'Spieltyp, Spielsituation und Ereignisse aus belegten Signalen erkennen.' },
  { id: 'interaction-ai', name: 'Interaction AI', purpose: 'Zuschaueraktionen und Challenges passend zum Spiel entwerfen.' },
  { id: 'overlay-ai', name: 'Overlay AI', purpose: 'Overlay-, Ranglisten- und Animationskonzepte vorbereiten.' },
  { id: 'event-ai', name: 'Event AI', purpose: 'Freigegebene LIVE-Ereignisse zu sicheren Aktionsvorschlägen zuordnen.' },
  { id: 'balance-ai', name: 'Balance AI', purpose: 'Fairness, Missbrauchsrisiken und Spielbalance bewerten.' },
  { id: 'learning-ai', name: 'Learning AI', purpose: 'Ergebnisse auswerten und überprüfbare Verbesserungen ableiten.' }
]);

const MAX_TEXT = 4000;
const SOURCE_TYPES = new Set(['manual', 'screen_capture', 'ocr', 'game_api', 'audio_transcript', 'capture_card']);

function boundedText(value, max = MAX_TEXT) {
  return typeof value === 'string' ? value.trim().slice(0, max) : '';
}

function normalizeObservation(input = {}) {
  if (!input || typeof input !== 'object' || Array.isArray(input)) {
    return { ok: false, error: 'Spielbeobachtung muss ein Objekt sein.' };
  }
  const gameTitle = boundedText(input.gameTitle, 160);
  const sourceType = SOURCE_TYPES.has(input.sourceType) ? input.sourceType : 'manual';
  const evidence = boundedText(input.evidence, MAX_TEXT);
  const platform = boundedText(input.platform, 80) || 'unbekannt';
  const signals = Array.isArray(input.availableSignals)
    ? [...new Set(input.availableSignals.filter(item =>
        ['video', 'ocr', 'audio', 'game_api', 'window_title'].includes(item)))].slice(0, 6)
    : [];
  if (!gameTitle) return { ok: false, error: 'Bitte den erkannten oder gespielten Titel angeben.' };
  if (!evidence && signals.length === 0) {
    return { ok: false, error: 'Es fehlen Beobachtungsdaten. Keine Spielsituation wird ohne Belege erfunden.' };
  }
  return {
    ok: true,
    observation: {
      gameTitle,
      platform,
      sourceType,
      evidence,
      availableSignals: signals,
      observedAt: new Date().toISOString()
    }
  };
}

function buildAgentTasks(observation) {
  return AGENTS.map(agent => ({
    id: agent.id,
    name: agent.name,
    purpose: agent.purpose,
    status: 'awaiting_ai_executor',
    input: {
      gameTitle: observation.gameTitle,
      platform: observation.platform,
      sourceType: observation.sourceType,
      evidence: observation.evidence,
      availableSignals: observation.availableSignals
    },
    constraints: [
      'Nur aus den übermittelten Belegen schließen.',
      'Unsicherheit ausdrücklich kennzeichnen; keine Spiel- oder Plattform-API erfinden.',
      'Keine Spielprozesse manipulieren und keine Anti-Cheat-Schutzmaßnahmen umgehen.',
      'LIVE-Aktionen nur als Vorschlag ausgeben; Ausführung benötigt eine Freigabe der Streamiov-Regie.',
      'TikTok-Ereignisse nur verarbeiten, wenn ein offizieller, tatsächlich verfügbarer Ereignisadapter sie liefert.'
    ]
  }));
}

function createGameAiAnalysis(input) {
  const normalized = normalizeObservation(input);
  if (!normalized.ok) return normalized;
  const observation = normalized.observation;
  return {
    ok: true,
    status: 'analysis_input_prepared',
    game: {
      title: observation.gameTitle,
      platform: observation.platform,
      detection: observation.sourceType === 'manual' ? 'manually_identified' : 'source_identified',
      evidenceAvailable: Boolean(observation.evidence),
      signals: observation.availableSignals
    },
    agents: buildAgentTasks(observation),
    specialistDirectory: buildSpecialistDirectory(),
    limitations: [
      'Dies ist die validierte Übergabe an die sechs KI-Bereiche, noch keine bestätigte Spielanalyse.',
      'Automatische Erkennung benötigt eine aktive Capture-/OCR-/Audio- oder offizielle Game-API-Quelle.',
      'Die KI-Ausführung benötigt einen verbundenen und getesteten Agenten-Ausführer im Streamiov Core.'
    ]
  };
}

module.exports = { AGENTS, normalizeObservation, buildAgentTasks, createGameAiAnalysis };
