'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { AGENTS, normalizeObservation, createGameAiAnalysis } = require('./game-ai-engine');

test('rejects missing game title and unsupported observation shapes', () => {
  assert.equal(normalizeObservation({ evidence: 'round won' }).ok, false);
  assert.equal(normalizeObservation('not-an-object').ok, false);
});

test('requires actual evidence or declared observation signals', () => {
  assert.equal(normalizeObservation({ gameTitle: 'Example Game' }).ok, false);
  assert.equal(normalizeObservation({
    gameTitle: 'Example Game',
    availableSignals: ['video', 'not-supported', 'video']
  }).observation.availableSignals.length, 1);
});

test('prepares all six specialized agents without claiming analysis execution', () => {
  const result = createGameAiAnalysis({
    gameTitle: 'Example Game',
    platform: 'Windows 11',
    sourceType: 'screen_capture',
    evidence: 'Round ended; score 3:1',
    availableSignals: ['video', 'ocr']
  });
  assert.equal(result.ok, true);
  assert.equal(result.status, 'analysis_input_prepared');
  assert.deepEqual(result.agents.map(agent => agent.id), AGENTS.map(agent => agent.id));
  assert.ok(result.agents.every(agent => agent.status === 'awaiting_ai_executor'));
  assert.ok(result.limitations.some(item => item.includes('noch keine bestätigte Spielanalyse')));
});

test('bounds untrusted observation text and removes unknown signal names', () => {
  const result = normalizeObservation({
    gameTitle: 'G'.repeat(300),
    sourceType: 'unknown',
    evidence: 'E'.repeat(9000),
    availableSignals: ['audio', 'shell', 'game_api']
  });
  assert.equal(result.ok, true);
  assert.equal(result.observation.gameTitle.length, 160);
  assert.equal(result.observation.evidence.length, 4000);
  assert.deepEqual(result.observation.availableSignals, ['audio', 'game_api']);
});
