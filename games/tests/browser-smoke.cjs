'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const { chromium } = require('playwright');

const root = path.resolve(__dirname, '..', '..');
const gameUrl = id => pathToFileURL(path.join(root, 'games', id, 'index.html')).href;

test('three independent games load and complete core browser interactions', async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    // Neon Relay: start, countdown advances, restart remains available.
    {
      const page = await browser.newPage({ viewport: { width: 1100, height: 820 } });
      await page.goto(gameUrl('neon-relay'));
      await page.getByRole('button', { name: 'Spiel starten' }).click();
      await page.waitForTimeout(1400);
      const time = Number(await page.locator('#time').textContent());
      assert.ok(time < 60 && time >= 58, 'Neon Relay timer must advance after start');
      assert.equal(await page.locator('canvas#game').count(), 1);
      await page.close();
    }

    // Echo Grid: observe the random sequence as it is displayed, then repeat it.
    {
      const page = await browser.newPage({ viewport: { width: 900, height: 900 } });
      await page.goto(gameUrl('echo-grid'));
      await page.getByRole('button', { name: 'START' }).click();
      const observed = [];
      const deadline = Date.now() + 10000;
      let previous = -1;
      while (Date.now() < deadline) {
        const active = await page.locator('.tile.lit').evaluateAll(nodes =>
          nodes.length ? Array.from(nodes[0].parentElement.children).indexOf(nodes[0]) : -1
        );
        if (active >= 0 && active !== previous) observed.push(active);
        previous = active;
        const status = await page.locator('#status').textContent();
        if (status.includes('Jetzt bist du dran!')) break;
        await page.waitForTimeout(35);
      }
      assert.equal(await page.locator('#status').textContent(), 'Jetzt bist du dran!');
      assert.equal(observed.length, 1, 'first Echo Grid round must show exactly one tile');
      await page.locator('.tile').nth(observed[0]).click();
      await page.waitForFunction(() => document.querySelector('#level').textContent === '2', null, { timeout: 5000 });
      await page.waitForFunction(() => document.querySelector('#status').textContent === 'Jetzt bist du dran!', null, { timeout: 10000 });
      assert.equal(await page.locator('#level').textContent(), '2', 'Echo Grid must advance to round two');
      await page.close();
    }

    // Pulse Defender: start and move/fire using keyboard; game remains active.
    {
      const page = await browser.newPage({ viewport: { width: 1100, height: 820 } });
      await page.goto(gameUrl('pulse-defender'));
      await page.getByRole('button', { name: 'VERTEIDIGEN' }).click();
      await page.keyboard.down('ArrowLeft');
      await page.keyboard.down('Space');
      await page.waitForTimeout(800);
      await page.keyboard.up('ArrowLeft');
      await page.keyboard.up('Space');
      assert.equal(await page.locator('canvas#field').count(), 1);
      assert.ok(Number(await page.locator('#shield').textContent()) > 0);
      assert.ok(Number(await page.locator('#wave').textContent()) >= 1);
      await page.close();
    }
  } finally {
    await browser.close();
  }
});
