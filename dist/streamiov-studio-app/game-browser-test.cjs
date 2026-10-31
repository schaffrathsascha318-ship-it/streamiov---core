const { app, BrowserWindow } = require('electron');
const path = require('path');

app.disableHardwareAcceleration();

app.whenReady().then(async () => {
  const win = new BrowserWindow({
    show: true,
    width: 1280,
    height: 800,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      backgroundThrottling: false
    }
  });

  try {
    const game = path.join(
      process.env.HOME,
      'streamiov/games/ai_created/streamiov-executor-pr-fspiel-eeb078/index.html'
    );

    await win.loadFile(game);

    const result = await win.webContents.executeJavaScript(`
      (async () => {
        const errors = [];
        let frames = 0;

        window.addEventListener('error', e => {
          errors.push(e.message || 'Unbekannter JavaScript-Fehler');
        });

        const originalRAF = window.requestAnimationFrame.bind(window);
        window.requestAnimationFrame = callback =>
          originalRAF(timestamp => {
            frames++;
            try {
              callback(timestamp);
            } catch (e) {
              errors.push(String(e.stack || e));
            }
          });

        const play = document.querySelector('#play');
        const score = document.querySelector('#score');

        if (!play) return { ok: false, reason: 'Startknopf fehlt' };

        play.click();
        await new Promise(resolve => setTimeout(resolve, 1800));

        const result = {
          title: document.title,
          introHidden: document.querySelector('#intro').hidden,
          frames,
          score: score?.textContent ?? 'fehlt',
          errors
        };

        const pause = document.querySelector('#pause');
        if (pause) {
          pause.click();
          result.pauseLabel = pause.textContent.trim();
        }

        return result;
      })()
    `);

    console.log('SPIEL-LAUFZEIT:', JSON.stringify(result));
  } catch (e) {
    console.error('TESTFEHLER:', e.stack || e);
    process.exitCode = 1;
  } finally {
    setTimeout(() => {
      win.destroy();
      app.quit();
    }, 300);
  }
});
