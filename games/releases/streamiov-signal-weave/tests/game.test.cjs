'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {SignalWeaveGame, LEVELS, LEVEL_COUNT, WIDTH} = require('../engine.js');

function solveCurrentLevel(game) {
  const route = LEVELS[game.levelIndex];
  route.path.slice(1, -1).forEach(([x, y], index) => {
    const turns = route.scramble[index] || 0;
    for (let turn = 0; turn < ((4 - turns) % 4) && game.phase === 'playing'; turn += 1) {
      game.rotate(x, y);
    }
  });
}

test('all authored puzzles begin unsolved and fit the 5 by 5 board', () => {
  assert.equal(LEVEL_COUNT, 3);
  for (let index = 0; index < LEVEL_COUNT; index += 1) {
    const game = new SignalWeaveGame();
    while (game.levelIndex < index) {
      game.start();
      solveCurrentLevel(game);
      game.nextLevel();
    }
    game.start();
    assert.equal(game.getBoard().length, WIDTH);
    assert.equal(game.getBoard().every((row) => row.length === WIDTH), true);
    assert.equal(game.phase, 'playing');
    assert.equal(game.isConnected(), false, `Level ${index + 1} must not start solved.`);
  }
});

test('valid solution rotates each path tile to connect source and target', () => {
  const game = new SignalWeaveGame();
  for (let level = 0; level < LEVEL_COUNT; level += 1) {
    if (game.phase === 'intro') game.start();
    solveCurrentLevel(game);
    assert.equal(game.phase, 'level_complete', `Level ${level + 1} did not solve.`);
    assert.equal(game.isConnected(), true);
    if (level < LEVEL_COUNT - 1) {
      assert.equal(game.nextLevel(), true);
      assert.equal(game.attempts, 0);
    }
  }
  assert.equal(game.nextLevel(), true);
  assert.equal(game.phase, 'victory');
});

test('empty cells and endpoints are fixed; invalid coordinates are ignored', () => {
  const game = new SignalWeaveGame();
  game.start();
  assert.equal(game.rotate(0, 2), false);
  assert.equal(game.rotate(4, 2), false);
  assert.equal(game.rotate(0, 0), false);
  assert.equal(game.rotate(-1, 2), false);
  assert.equal(game.attempts, 0);
});

test('game state is independent across instances and restart restores level one', () => {
  const first = new SignalWeaveGame();
  const second = new SignalWeaveGame();
  first.start();
  first.rotate(1, 2);
  assert.equal(first.attempts, 1);
  assert.equal(second.attempts, 0);
  first.restart();
  assert.equal(first.phase, 'intro');
  assert.equal(first.levelIndex, 0);
  assert.equal(first.attempts, 0);
  assert.equal(first.isConnected(), false);
});

test('browser build is responsive, locally branded, touch-ready, and has no remote assets', () => {
  const html = fs.readFileSync(path.join(__dirname, '../index.html'), 'utf8');
  const gameManifest = JSON.parse(fs.readFileSync(path.join(__dirname, '../game.json'), 'utf8'));
  const inlineScript = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(match => match[1]).at(-1);
  assert.ok(inlineScript);
  assert.doesNotThrow(() => new Function(inlineScript));
  assert.match(html, /assets\/streamiov-game-intro\.js/);
  assert.match(html, /playIntro/);
  assert.match(html, /playOutro/);
  assert.match(html, /prefers-reduced-motion/);
  assert.match(html, /viewport-fit=cover/);
  assert.match(html, /min\(75vh,900px\)/);
  assert.match(html, /touch-action:manipulation/);
  assert.equal([...html.matchAll(/(?:src|href)=["']https?:/g)].length, 0);
  assert.match(gameManifest.display.hd_design_target, /verification pending/);
  assert.deepEqual(gameManifest.dependencies, []);
});
