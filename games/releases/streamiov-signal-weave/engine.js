/* StreamioV Signal Weave: deterministic offline pipe-routing puzzle engine. */
(function (root, factory) {
  'use strict';
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  root.StreamioVSignalWeave = api;
})(globalThis, function () {
  'use strict';

  const WIDTH = 5;
  const DIRS = Object.freeze(['N', 'E', 'S', 'W']);
  const DELTA = Object.freeze({ N: [0, -1], E: [1, 0], S: [0, 1], W: [-1, 0] });
  const OPPOSITE = Object.freeze({ N: 'S', E: 'W', S: 'N', W: 'E' });
  const route = (title, scramble, points) => Object.freeze({
    title,
    scramble: Object.freeze(scramble),
    path: Object.freeze(points.map((point) => Object.freeze(point)))
  });
  const LEVELS = Object.freeze([
    route('Der erste Impuls', [1, 1, 1], [[0, 2], [1, 2], [2, 2], [3, 2], [4, 2]]),
    route('Knick im Signal', [1, 2, 1, 3, 2], [[0, 0], [1, 0], [2, 0], [2, 1], [2, 2], [3, 2], [4, 2]]),
    route('Langer Umweg', [1, 3, 2, 1, 2, 3, 1, 2, 1, 3, 2], [[0, 4], [0, 3], [0, 2], [1, 2], [2, 2], [2, 1], [2, 0], [3, 0], [4, 0], [4, 1], [4, 2], [4, 3], [4, 4]])
  ]);

  function directionBetween(from, to) {
    const dx = to[0] - from[0], dy = to[1] - from[1];
    return DIRS.find((dir) => DELTA[dir][0] === dx && DELTA[dir][1] === dy) || null;
  }

  function rotateConnections(connections, turns) {
    const shift = ((turns % 4) + 4) % 4;
    return connections.map((dir) => DIRS[(DIRS.indexOf(dir) + shift) % 4]);
  }

  function createBoard(levelIndex) {
    const level = LEVELS[levelIndex];
    if (!level) throw new RangeError('Unbekanntes Level.');
    const board = Array.from({ length: WIDTH }, () => Array.from({ length: WIDTH }, () => ({ type: 'empty', connections: [], turns: 0 })));
    const path = level.path;
    const occupied = new Set();
    path.forEach((position, index) => {
      const [x, y] = position;
      if (x < 0 || x >= WIDTH || y < 0 || y >= WIDTH) throw new Error('Levelpfad liegt außerhalb des Spielfelds.');
      const key = `${x},${y}`;
      if (occupied.has(key)) throw new Error('Levelpfad darf keine Felder doppelt belegen.');
      occupied.add(key);
      let connections;
      let type;
      if (index === 0) {
        type = 'source';
        connections = [directionBetween(position, path[index + 1])];
      } else if (index === path.length - 1) {
        type = 'target';
        connections = [directionBetween(position, path[index - 1])];
      } else {
        type = 'pipe';
        connections = [directionBetween(position, path[index - 1]), directionBetween(position, path[index + 1])];
      }
      if (connections.some((dir) => !dir)) throw new Error('Levelpfad enthält nicht benachbarte Felder.');
      const scramble = type === 'pipe' ? level.scramble[index - 1] || 0 : 0;
      board[y][x] = { type, connections: rotateConnections(connections, scramble), turns: scramble % 4 };
    });
    return board;
  }

  class SignalWeaveGame {
    constructor() {
      this.levelIndex = 0;
      this.attempts = 0;
      this.phase = 'intro';
      this.board = createBoard(this.levelIndex);
    }

    get level() { return LEVELS[this.levelIndex]; }

    getBoard() {
      return this.board.map((row) => row.map((cell) => ({
        type: cell.type,
        connections: [...cell.connections],
        turns: cell.turns
      })));
    }

    start() {
      if (this.phase === 'intro' || this.phase === 'level_complete') this.phase = 'playing';
    }

    rotate(x, y) {
      if (this.phase !== 'playing' || !Number.isInteger(x) || !Number.isInteger(y) || x < 0 || x >= WIDTH || y < 0 || y >= WIDTH) return false;
      const cell = this.board[y][x];
      if (cell.type !== 'pipe') return false;
      cell.connections = rotateConnections(cell.connections, 1);
      cell.turns = (cell.turns + 1) % 4;
      this.attempts += 1;
      if (this.isConnected()) this.phase = 'level_complete';
      return true;
    }

    isConnected() {
      const queue = [];
      const visited = new Set();
      for (let y = 0; y < WIDTH; y += 1) for (let x = 0; x < WIDTH; x += 1) {
        if (this.board[y][x].type === 'source') queue.push([x, y]);
      }
      while (queue.length) {
        const [x, y] = queue.shift();
        const key = `${x},${y}`;
        if (visited.has(key)) continue;
        visited.add(key);
        const cell = this.board[y][x];
        if (cell.type === 'target') return true;
        for (const direction of cell.connections) {
          const [dx, dy] = DELTA[direction];
          const nx = x + dx, ny = y + dy;
          if (nx < 0 || nx >= WIDTH || ny < 0 || ny >= WIDTH) continue;
          const next = this.board[ny][nx];
          if (next.connections.includes(OPPOSITE[direction])) queue.push([nx, ny]);
        }
      }
      return false;
    }

    nextLevel() {
      if (this.phase !== 'level_complete') return false;
      if (this.levelIndex === LEVELS.length - 1) {
        this.phase = 'victory';
        return true;
      }
      this.levelIndex += 1;
      this.attempts = 0;
      this.board = createBoard(this.levelIndex);
      this.phase = 'playing';
      return true;
    }

    restart() {
      this.levelIndex = 0;
      this.attempts = 0;
      this.board = createBoard(0);
      this.phase = 'intro';
    }
  }

  return Object.freeze({ SignalWeaveGame, WIDTH, LEVEL_COUNT: LEVELS.length, LEVELS });
});
