'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { analyseFrame, compareFrames, classify, highlightScore } = require('./gameplay-vision');

function frame(red, green, blue) {
  const width = 16;
  const height = 9;
  const data = new Uint8ClampedArray(width * height * 4);
  for (let index = 0; index < width * height; index += 1) {
    data[index * 4] = red;
    data[index * 4 + 1] = green;
    data[index * 4 + 2] = blue;
    data[index * 4 + 3] = 255;
  }
  return { width, height, data: data.buffer };
}

test('frame analysis measures real pixel evidence without storing the image', () => {
  const bright = analyseFrame(frame(220, 180, 40));
  assert.equal(bright.width, 16);
  assert.ok(bright.meanLuminance > 100);
  assert.ok(bright.warmRatio > 0.9);
  assert.equal(bright.frame.data.length, 16 * 9 * 4);
});

test('frame comparison and classification stay deterministic and bounded', () => {
  const first = analyseFrame(frame(5, 5, 5));
  const second = analyseFrame(frame(230, 230, 230));
  const initial = compareFrames(first, null);
  const same = compareFrames(first, first);
  const changed = compareFrames(second, first);
  assert.equal(initial.available, false);
  assert.equal(same.changedRatio, 0);
  assert.ok(changed.changedRatio > 0.5);
  assert.equal(classify(first, initial).situation, 'dunkel_oder_ladebildschirm');
  assert.equal(classify(second, changed).situation, 'szenenwechsel');
  assert.ok(highlightScore(second, changed, classify(second, changed)) <= 100);
});
