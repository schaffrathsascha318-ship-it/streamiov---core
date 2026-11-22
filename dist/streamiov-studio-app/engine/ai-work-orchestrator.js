'use strict';

/**
 * Registry of Streamiov's existing development specialists.
 * The game-LIVE agents are additive and do not replace these roles.
 * This registry describes routing contracts; execution is provided by the
 * authenticated Streamiov Core task runner, not by this local registry.
 */
const DEVELOPMENT_SPECIALISTS = Object.freeze([
  { id: 'game', name: 'Game-KI', purpose: 'Streamiov-Spiele entwickeln und fremde laufende Spiele analysieren; Spielmechaniken, Level und LIVE-Erweiterungen vorbereiten.' },
  { id: 'code', name: 'Code-KI', purpose: 'Programmcode entwickeln, refaktorieren und technische Änderungen vorbereiten.' },
  { id: 'design', name: 'Design-KI', purpose: 'Originalgrafiken, UI, Overlays, 3D-Objekte und Animationen gestalten.' },
  { id: 'gifts', name: 'Gifts-KI', purpose: 'Eigenständige Streamiov-Geschenke und passende Animationen entwickeln.' },
  { id: 'testing', name: 'Testing-KI', purpose: 'Änderungen unabhängig testen, Regressionen erkennen und Ergebnisse dokumentieren.' },
  { id: 'repair', name: 'Repair-KI', purpose: 'Bestätigte Fehler gezielt beheben, ohne unabhängige Änderungen zu überschreiben.' },
  { id: 'integration', name: 'Integration-KI', purpose: 'Geprüfte Module und Schnittstellen kontrolliert integrieren.' },
  { id: 'studio', name: 'Studio-KI', purpose: 'Streamiov Studio, Regie, Medienpipeline und Geräteintegration weiterentwickeln.' },
  { id: 'general', name: 'General-KI', purpose: 'Allgemeine, keinem Spezialgebiet zugeordnete Aufgaben analysieren und koordinieren.' }
]);

const GAME_LIVE_AGENTS = Object.freeze([
  { id: 'game-analyzer', name: 'Game Analyzer', purpose: 'Fremde und eigene Spiele sowie belegte Spielsituationen analysieren.' },
  { id: 'interaction-ai', name: 'Interaction AI', purpose: 'Zuschaueraktionen, Challenges und Community-Interaktionen entwickeln.' },
  { id: 'overlay-ai', name: 'Overlay AI', purpose: 'Spielbezogene Overlays, Ranglisten und Animationen vorbereiten.' },
  { id: 'event-ai', name: 'Event AI', purpose: 'Verfügbare und freigegebene LIVE-Ereignisse verarbeiten.' },
  { id: 'balance-ai', name: 'Balance AI', purpose: 'Fairness, Missbrauchsrisiken und Spielbalance bewerten.' },
  { id: 'learning-ai', name: 'Learning AI', purpose: 'Freigegebene Ergebnisse auswerten und Verbesserungen ableiten.' }
]);

function buildSpecialistDirectory() {
  return {
    development: DEVELOPMENT_SPECIALISTS.map(item => ({ ...item, status: 'registered_role_execution_not_verified' })),
    gameLive: GAME_LIVE_AGENTS.map(item => ({ ...item, status: 'registered_role_execution_not_verified' }))
  };
}

module.exports = { DEVELOPMENT_SPECIALISTS, GAME_LIVE_AGENTS, buildSpecialistDirectory };
