'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { DEVELOPMENT_SPECIALISTS, GAME_LIVE_AGENTS, buildSpecialistDirectory } = require('./ai-work-orchestrator');

test('preserves all nine existing development specialist roles', () => {
  assert.deepEqual(DEVELOPMENT_SPECIALISTS.map(item => item.id), [
    'game', 'code', 'design', 'gifts', 'testing', 'repair', 'integration', 'studio', 'general'
  ]);
});

test('adds six game LIVE agents without replacing development specialists', () => {
  assert.equal(GAME_LIVE_AGENTS.length, 6);
  const directory = buildSpecialistDirectory();
  assert.equal(directory.development.length, 9);
  assert.equal(directory.gameLive.length, 6);
  assert.equal(directory.development[0].id, 'game');
  assert.equal(directory.gameLive[0].id, 'game-analyzer');
});

test('does not claim autonomous execution before a Core executor is verified', () => {
  const directory = buildSpecialistDirectory();
  assert.ok([...directory.development, ...directory.gameLive]
    .every(item => item.status === 'registered_role_execution_not_verified'));
});
