'use strict';

const MAX_TEXT = 600;

function clean(value) {
  return typeof value === 'string' ? value.trim().slice(0, MAX_TEXT) : '';
}

function number(value, fallback = 0) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function summariseStats(stats = {}) {
  const sessionCount = Math.max(0, Math.floor(number(stats.sessionCount)));
  const observationCount = Math.max(0, Math.floor(number(stats.observationCount)));
  const highlights = Math.max(0, Math.floor(number(stats.highlightCount)));
  const wins = Math.max(0, Math.floor(number(stats.wins)));
  const losses = Math.max(0, Math.floor(number(stats.losses)));
  const reaction = number(stats.averageReactionMs);
  const strategyCount = Array.isArray(stats.strategy) ? stats.strategy.length : 0;
  const parts = [
    `${sessionCount} Sitzungen`,
    `${observationCount} Beobachtungen`,
    `${highlights} Highlights`,
    `Signal ${wins}:${losses}`,
  ];
  if (reaction > 0) parts.push(`Reaktion ${Math.round(reaction)} ms`);
  if (strategyCount > 0) parts.push(`${strategyCount} Empfehlungen`);
  return 'Spielstand: ' + parts.join(' · ') + '.';
}

function recommendations({ stats = {}, situations = [], profile = {} } = {}) {
  const result = [];
  const observationCount = Math.max(0, Math.floor(number(stats.observationCount)));
  const highlightCount = Math.max(0, Math.floor(number(stats.highlightCount)));
  const wins = Math.max(0, Math.floor(number(stats.wins)));
  const losses = Math.max(0, Math.floor(number(stats.losses)));
  const reaction = number(stats.averageReactionMs);
  const longestSession = Math.max(0, number(stats.longestSessionMs));
  const situationCounts = stats.situationCounts || {};
  const danger = Math.max(0, Math.floor(number(situationCounts.gefahr)));
  const objective = Math.max(0, Math.floor(number(situationCounts.ziel_oder_belohnung)));
  const action = Math.max(0, Math.floor(number(situationCounts.aktion)));
  const goals = Array.isArray(profile.goals) ? profile.goals : [];
  const add = (kind, priority, title, detail, basis, confidence) => result.push({
    id: `${kind}-${result.length + 1}`,
    kind,
    priority,
    title,
    detail,
    basis,
    confidence: Number(Math.max(0.4, Math.min(0.9, confidence)).toFixed(2)),
  });
  if (observationCount < 4) {
    add('datierung', 'low', 'Mehr Beobachtungen sammeln',
      'Die Analyse stützt sich auf wenige Ereignisse. Erfasse weitere Bilder oder Beobachtungen.',
      `${observationCount} Beobachtungen vorhanden.`, 0.55);
  }
  if (reaction > 380) {
    add('reaktion', 'high', 'Reaktionszeit trainieren',
      'Wiederhole kurze Zielwechsel und markiere die Reaktion im Anschluss als Beobachtung.',
      `Gemittelte gemeldete Reaktion: ${Math.round(reaction)} ms.`, 0.72);
  } else if (reaction > 0 && reaction < 260) {
    add('reaktion', 'low', 'Reaktionsvorteil halten',
      'Die aktuelle Reaktionszeit ist stabil. Behalte die bestehende Pausenroutine bei.',
      `Gemittelte gemeldete Reaktion: ${Math.round(reaction)} ms.`, 0.64);
  }
  if (danger > 1 && reaction > 300) {
    add('gefahr', 'high', 'Gefahrensituationen früher erkennen',
      'Prüfe in Replays die Frames vor Gefahr-Markierungen und notiere ein fixes Signal.',
      `${danger} Gefahrensituationen, Reaktionsmittelwert ${Math.round(reaction)} ms.`, 0.7);
  }
  if (objective === 0 && observationCount >= 4) {
    add('ziel', 'medium', 'Zielfokus protokollieren',
      'Markiere erreichte Ziele aktiv, damit Fortschritt und Belohnungen nicht verloren gehen.',
      'Keine ziel_oder_belohnung-Situation im aktuellen Fenster.', 0.6);
  }
  if (action > 2 && highlightCount === 0) {
    add('highlight', 'medium', 'Aktions-Highlights markieren',
      'Die Erkennung meldet Bewegung, aber keine Highlights. Prüfe die Highlight-Schwelle.',
      `${action} Aktionssituationen, 0 Highlights.`, 0.66);
  }
  if (wins + losses > 0) {
    const rate = wins / (wins + losses);
    if (rate < 0.4) {
      add('ergebnis', 'high', 'Ergebnisbilanz stabilisieren',
        'Analysiere die letzten fünf Beobachtungen vor Niederlagen und teste eine konkrete Anpassung.',
        `Signalquote ${Math.round(rate * 100)} %.`, 0.68);
    } else if (rate >= 0.6) {
      add('ergebnis', 'low', 'Erfolgsroutine dokumentieren',
        'Halte die erfolgreiche Routine als Profilnotiz fest und prüfe sie im nächsten Replay.',
        `Signalquote ${Math.round(rate * 100)} %.`, 0.62);
    }
  }
  if (longestSession > 45 * 60 * 1000) {
    add('pause', 'medium', 'Sessionlänge begrenzen',
      'Die längste aufgezeichnete Session überschreitet 45 Minuten. Plane eine kurze Pause ein.',
      `Längste Session ${Math.round(longestSession / 60000)} Minuten.`, 0.64);
  }
  for (const goal of goals.slice(0, 3)) {
    const text = clean(goal);
    if (!text) continue;
    add('ziel_profil', 'medium', `Ziel verfolgen: ${text}`,
      'Vergleiche das gewünschte Ziel mit den letzten Beobachtungen und dem Replay-Fortschritt.',
      `Profilziel: ${text}`, 0.58);
  }
  if (!result.length) {
    add('basis', 'low', 'Weiter beobachten',
      'Es liegen noch keine auffälligen Muster vor. Die Analyse bleibt lokal und nachvollziehbar.',
      `${observationCount} Beobachtungen ausgewertet.`, 0.52);
  }
  const priority = { high: 0, medium: 1, low: 2 };
  return result.sort((a, b) => priority[a.priority] - priority[b.priority] || b.confidence - a.confidence).slice(0, 8);
}

function voiceCommand(text) {
  const command = clean(text).toLocaleLowerCase('de-DE');
  if (!command) return { ok: false, error: 'Kein Sprachbefehl erkannt.' };
  if (/^(highlight|markiere highlight|highlight markieren)/.test(command)) {
    return { ok: true, intent: 'highlight', reply: 'Highlight wird markiert.' };
  }
  if (/(statistik|statistiken|wie l[äa]uft|spielstand)/.test(command)) {
    return { ok: true, intent: 'stats', reply: 'Ich lese den Spielstand vor.' };
  }
  if (/(strategie|tipp|empfehlung|was soll ich)/.test(command)) {
    return { ok: true, intent: 'strategy', reply: 'Ich nenne die wichtigste Empfehlung.' };
  }
  if (/^notiz\s+(.+)/.test(command)) {
    return { ok: true, intent: 'note', reply: 'Notiz wird gespeichert.', data: { text: clean(command.replace(/^notiz\s+/, '')) } };
  }
  if (/^ziel\s+(.+)/.test(command)) {
    return { ok: true, intent: 'goal', reply: 'Ziel wird gespeichert.', data: { text: clean(command.replace(/^ziel\s+/, '')) } };
  }
  if (/(bericht|zusammenfassung)/.test(command)) {
    return { ok: true, intent: 'report', reply: 'Ich erstelle einen Kurzbericht.' };
  }
  return { ok: false, error: 'Befehl nicht erkannt. Sag zum Beispiel Statistik, Strategie oder Highlight.' };
}

module.exports = { recommendations, summariseStats, voiceCommand };
