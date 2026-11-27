'use strict';

const MAX_WIDTH = 320;
const MAX_HEIGHT = 180;
const MIN_WIDTH = 8;
const MIN_HEIGHT = 8;

function clamp(value, min, max) {
  const number = Number(value);
  return Number.isFinite(number) ? Math.max(min, Math.min(max, Math.round(number))) : min;
}

function normaliseFrame(payload = {}) {
  const width = clamp(payload.width, MIN_WIDTH, MAX_WIDTH);
  const height = clamp(payload.height, MIN_HEIGHT, MAX_HEIGHT);
  const expected = width * height * 4;
  const raw = payload.data;
  let data;
  if (raw instanceof Uint8Array) data = raw;
  else if (raw instanceof Uint8ClampedArray) data = new Uint8Array(raw.buffer, raw.byteOffset, raw.byteLength);
  else if (raw instanceof ArrayBuffer) data = new Uint8Array(raw);
  else if (Array.isArray(raw)) data = Uint8Array.from(raw);
  else throw new TypeError('Bilddaten fehlen.');
  if (data.length < expected) throw new TypeError('Bilddaten sind unvollständig.');
  return { width, height, data: data.subarray(0, expected) };
}

function analyseFrame(payload) {
  const frame = normaliseFrame(payload);
  const { width, height, data } = frame;
  let lumSum = 0;
  let lumSquare = 0;
  let edgeCount = 0;
  let hudCount = 0;
  let dark = 0;
  let red = 0;
  let green = 0;
  let blue = 0;
  let cyan = 0;
  let warm = 0;
  const pixels = width * height;
  for (let index = 0; index < pixels; index += 1) {
    const offset = index * 4;
    const r = data[offset];
    const g = data[offset + 1];
    const b = data[offset + 2];
    const lum = 0.2126 * r + 0.7152 * g + 0.0722 * b;
    lumSum += lum;
    lumSquare += lum * lum;
    if (lum < 24) dark += 1;
    if (r > g * 1.3 && r > b * 1.3 && r > 55) red += 1;
    if (g > r * 1.2 && g > b * 1.1 && g > 55) green += 1;
    if (b > r * 1.25 && b > g * 1.1 && b > 55) blue += 1;
    if (g > r * 1.15 && b > r * 1.25 && g > 60) cyan += 1;
    if (r > b * 1.25 && g > b * 1.2 && r > 60) warm += 1;
    const x = index % width;
    const y = Math.floor(index / width);
    if (y < height * 0.12 || y > height * 0.88) hudCount += 1;
    if (x + 1 < width && y + 1 < height) {
      const right = (index + 1) * 4;
      const down = (index + width) * 4;
      const rightLum = 0.2126 * data[right] + 0.7152 * data[right + 1] + 0.0722 * data[right + 2];
      const downLum = 0.2126 * data[down] + 0.7152 * data[down + 1] + 0.0722 * data[down + 2];
      if (Math.abs(lum - rightLum) + Math.abs(lum - downLum) > 42) edgeCount += 1;
    }
  }
  const mean = lumSum / pixels;
  const variance = Math.max(0, lumSquare / pixels - mean * mean);
  const ratio = (value) => Number((value / pixels).toFixed(4));
  return Object.freeze({
    width,
    height,
    meanLuminance: Number(mean.toFixed(2)),
    luminanceDeviation: Number(Math.sqrt(variance).toFixed(2)),
    edgeDensity: ratio(edgeCount),
    darkRatio: ratio(dark),
    redRatio: ratio(red),
    greenRatio: ratio(green),
    blueRatio: ratio(blue),
    cyanRatio: ratio(cyan),
    warmRatio: ratio(warm),
    meta: Object.freeze({ pixels, capturedAt: Date.now() }),
    frame,
  });
}

function compareFrames(current, previous) {
  const currentFrame = current?.frame || current;
  const previousFrame = previous?.frame || previous;
  if (!currentFrame || !previousFrame || previousFrame.width !== currentFrame.width || previousFrame.height !== currentFrame.height) {
    return Object.freeze({ available: false, changedRatio: 0, meanDelta: 0, centerChangedRatio: 0, hudChangedRatio: 0 });
  }
  const pixels = currentFrame.width * currentFrame.height;
  let changed = 0;
  let deltaSum = 0;
  let centerChanged = 0;
  let centerTotal = 0;
  let hudChanged = 0;
  let hudTotal = 0;
  for (let index = 0; index < pixels; index += 1) {
    const offset = index * 4;
    const delta = Math.abs(currentFrame.data[offset] - previousFrame.data[offset])
      + Math.abs(currentFrame.data[offset + 1] - previousFrame.data[offset + 1])
      + Math.abs(currentFrame.data[offset + 2] - previousFrame.data[offset + 2]);
    deltaSum += delta / 3;
    const x = index % currentFrame.width;
    const y = Math.floor(index / currentFrame.width);
    const isCenter = x > currentFrame.width * 0.25 && x < currentFrame.width * 0.75
      && y > currentFrame.height * 0.2 && y < currentFrame.height * 0.8;
    const isHud = y < currentFrame.height * 0.12 || y > currentFrame.height * 0.88;
    if (delta > 24) changed += 1;
    if (isCenter) {
      centerTotal += 1;
      if (delta > 24) centerChanged += 1;
    }
    if (isHud) {
      hudTotal += 1;
      if (delta > 24) hudChanged += 1;
    }
  }
  return Object.freeze({
    available: true,
    changedRatio: Number((changed / pixels).toFixed(4)),
    meanDelta: Number((deltaSum / pixels).toFixed(2)),
    centerChangedRatio: Number((centerChanged / Math.max(1, centerTotal)).toFixed(4)),
    hudChangedRatio: Number((hudChanged / Math.max(1, hudTotal)).toFixed(4)),
  });
}

function classify(metrics, diff) {
  const signals = [];
  if (metrics.meanLuminance < 14 && metrics.darkRatio > 0.8) {
    return { situation: 'dunkel_oder_ladebildschirm', confidence: 0.78, signals: ['low_light'] };
  }
  if (diff.available && diff.changedRatio > 0.55) {
    signals.push('scene_change');
    return { situation: 'szenenwechsel', confidence: 0.72, signals };
  }
  if (diff.available && diff.hudChangedRatio > 0.22 && diff.centerChangedRatio < 0.2) {
    signals.push('hud_update');
    return { situation: 'hud_oder_statusupdate', confidence: 0.7, signals };
  }
  if (metrics.redRatio > 0.22 && metrics.edgeDensity > 0.12) {
    signals.push('red_alert');
    return { situation: 'gefahr', confidence: 0.66, signals };
  }
  if (metrics.greenRatio > 0.24 || metrics.cyanRatio > 0.3) {
    signals.push('objective_color');
    return { situation: 'ziel_oder_belohnung', confidence: 0.62, signals };
  }
  if (metrics.edgeDensity > 0.2 && diff.available && diff.centerChangedRatio > 0.16) {
    signals.push('motion_and_detail');
    return { situation: 'aktion', confidence: 0.64, signals };
  }
  if (metrics.edgeDensity < 0.05 && diff.available && diff.changedRatio < 0.04) {
    signals.push('static_frame');
    return { situation: 'statisch_oder_menue', confidence: 0.6, signals };
  }
  return { situation: 'gameplay', confidence: 0.5, signals: ['general_play'] };
}

function highlightScore(metrics, diff, classification) {
  let score = Math.round(metrics.edgeDensity * 90 + metrics.meanLuminance * 0.2);
  if (diff.available) score += Math.round(diff.centerChangedRatio * 80 + diff.hudChangedRatio * 25);
  if (classification.situation === 'ziel_oder_belohnung') score += 22;
  if (classification.situation === 'gefahr') score += 16;
  if (classification.situation === 'szenenwechsel') score += 10;
  if (classification.situation === 'statisch_oder_menue') score -= 25;
  return Math.max(0, Math.min(100, score));
}

module.exports = { analyseFrame, compareFrames, classify, highlightScore, normaliseFrame };
