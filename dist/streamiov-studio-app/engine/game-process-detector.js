'use strict';

const { execFile } = require('node:child_process');
const { promisify } = require('node:util');

const execFileAsync = promisify(execFile);
const MAX_PROCESSES = 80;
const MAX_TEXT = 160;
const CONTROL_PATTERN = /[\u0000-\u001f\u007f]/g;
const GAME_PATTERN = /streamiov|neon.?relay|echo.?grid|pulse.?defender|signal.?weave|star.?defender|game|spiel|steam|epic|minecraft|valorant|fortnite|overwatch|counter.?strike|league.?of.?legends|gta|witcher|doom|portal|half.?life/i;
const OWN_GAME_PATTERN = /echo.?grid|neon.?relay|pulse.?defender|signal.?weave|star.?defender/i;

function clean(value, maxLength = MAX_TEXT) {
  return String(value ?? '').replace(CONTROL_PATTERN, '').trim().slice(0, maxLength);
}

function candidate(name, command) {
  const text = clean(name) + ' ' + clean(command);
  const ownGame = OWN_GAME_PATTERN.test(text);
  const likelyGame = GAME_PATTERN.test(text);
  const confidenceScore = ownGame ? 0.92 : likelyGame ? 0.68 : 0.12;
  return {
    detection: 'process_list',
    confidence: likelyGame ? 'possible' : 'unconfirmed',
    confidenceScore,
    likelyGame,
    streamiovGame: ownGame,
    source: ownGame ? 'streamiov' : 'external',
  };
}

function parsePosix(stdout) {
  const rows = [];
  for (const line of String(stdout).split(/\r?\n/)) {
    const match = line.match(/^\s*(\d+)\s+(\S+)\s+(.*)$/);
    if (!match) continue;
    const pid = Math.max(0, Math.round(Number(match[1]) || 0));
    const processName = clean(match[2].split('/').pop(), 80);
    const command = clean(match[3], MAX_TEXT);
    if (!processName) continue;
    rows.push({
      pid,
      processName,
      windowTitle: '',
      command,
      ...candidate(processName, command),
    });
  }
  return rows;
}

function parseCsvLine(line) {
  const result = [];
  let value = '';
  let quoted = false;
  for (let index = 0; index < line.length; index += 1) {
    const char = line[index];
    if (char === '"') {
      if (quoted && line[index + 1] === '"') {
        value += '"';
        index += 1;
      } else {
        quoted = !quoted;
      }
    } else if (char === ',' && !quoted) {
      result.push(value);
      value = '';
    } else {
      value += char;
    }
  }
  result.push(value);
  return result.map(item => clean(item));
}

function parseWindows(stdout) {
  const rows = [];
  for (const line of String(stdout).split(/\r?\n/)) {
    if (!line.trim()) continue;
    const fields = parseCsvLine(line);
    if (/^image\s*name$/i.test(fields[0] || '')) continue;
    const processName = (fields[0] || '').replace(/\.exe$/i, '');
    if (!processName) continue;
    const pid = Math.max(0, Math.round(Number(fields[1]) || 0));
    rows.push({
      pid,
      processName,
      windowTitle: '',
      command: clean(fields.join(' '), MAX_TEXT),
      ...candidate(processName, fields.join(' ')),
    });
  }
  return rows;
}

async function listRunningProcesses({ run = execFileAsync, platform = process.platform } = {}) {
  try {
    const result = platform === 'win32'
      ? await run('tasklist', ['/FO', 'CSV', '/NH'])
      : await run('ps', ['-eo', 'pid=,comm=,args=']);
    const rows = platform === 'win32' ? parseWindows(result.stdout) : parsePosix(result.stdout);
    const seen = new Set();
    return rows.filter(item => {
      const key = item.processName.toLocaleLowerCase();
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    }).sort((a, b) => {
      if (a.likelyGame !== b.likelyGame) return a.likelyGame ? -1 : 1;
      return a.processName.localeCompare(b.processName);
    }).slice(0, MAX_PROCESSES);
  } catch {
    return [];
  }
}

module.exports = { listRunningProcesses, parsePosix, parseWindows };
