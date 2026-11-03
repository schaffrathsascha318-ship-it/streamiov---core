/* Streamiov game intro. No external assets, fonts, services, or runtime dependencies. */
(function (root) {
  'use strict';

  const mark = '<svg class="sv-mark" viewBox="0 0 128 128" aria-hidden="true"><defs><linearGradient id="sv-signal" x1="24" y1="23" x2="103" y2="107" gradientUnits="userSpaceOnUse"><stop stop-color="#9b86ff"/><stop offset=".5" stop-color="#42e8ff"/><stop offset="1" stop-color="#74ffd1"/></linearGradient><linearGradient id="sv-play" x1="51" y1="40" x2="86" y2="88" gradientUnits="userSpaceOnUse"><stop stop-color="#e6ffff"/><stop offset="1" stop-color="#42e8ff"/></linearGradient></defs><path class="sv-orbit" d="M91 32a43 43 0 0 0-59 8M37 96a43 43 0 0 0 59-8" fill="none" stroke="url(#sv-signal)" stroke-linecap="round" stroke-width="7"/><path class="sv-triangle" d="M50 42.5c0-3.1 3.4-5 6.1-3.4l32.2 20.1a5.7 5.7 0 0 1 0 9.6L56.1 88.9c-2.7 1.7-6.1-.3-6.1-3.4V42.5Z" fill="url(#sv-play)"/><circle cx="94" cy="31" r="4" fill="#9b86ff"/><circle cx="34" cy="97" r="4" fill="#67f4e4"/></svg>';

  const css = `
    .sv-intro{position:fixed;inset:0;z-index:2147483000;display:grid;place-items:center;overflow:hidden;background:radial-gradient(ellipse at 50% 44%,#152340 0,#0b1020 43%,#050710 100%);color:#f5f7ff;font-family:Inter,"Avenir Next","Segoe UI",sans-serif;opacity:1;transition:opacity .65s ease}
    .sv-intro *{box-sizing:border-box}.sv-intro.is-leaving{opacity:0;pointer-events:none}
    .sv-intro__grid{position:absolute;inset:-50%;opacity:.22;background-image:linear-gradient(#78b8ff12 1px,transparent 1px),linear-gradient(90deg,#78b8ff12 1px,transparent 1px);background-size:64px 64px;transform:perspective(420px) rotateX(58deg) scale(1.5);animation:sv-grid 3.8s ease-out both}
    .sv-intro__halo{position:absolute;width:min(62vw,560px);aspect-ratio:1;border:1px solid #42e8ff26;border-radius:50%;box-shadow:0 0 90px #42e8ff12,inset 0 0 80px #8e7aff0a;animation:sv-halo 3.4s ease-out both}
    .sv-intro__content{position:relative;display:flex;flex-direction:column;align-items:center;text-align:center;padding:24px}
    .sv-mark{width:clamp(82px,15vw,138px);filter:drop-shadow(0 0 24px #42e8ff55);animation:sv-mark-in .9s cubic-bezier(.2,.8,.2,1) both}
    .sv-intro__brand{margin:16px 0 0;font-size:clamp(13px,2vw,18px);font-weight:750;letter-spacing:.34em;color:#cbd6ed;opacity:0;animation:sv-copy-in .55s .35s ease-out forwards}
    .sv-intro__rule{width:0;height:2px;margin:22px 0;background:linear-gradient(90deg,transparent,#9b86ff,#42e8ff,#74ffd1,transparent);box-shadow:0 0 18px #42e8ff;animation:sv-rule-in .7s .6s ease-out forwards}
    .sv-intro__title{margin:0;max-width:min(88vw,1000px);font-size:clamp(34px,8vw,84px);line-height:1.02;font-weight:800;letter-spacing:-.045em;text-wrap:balance;text-shadow:0 0 36px #42e8ff20;opacity:0;transform:translateY(16px);animation:sv-title-in .75s .72s cubic-bezier(.2,.8,.2,1) forwards}
    .sv-intro__tag{margin:18px 0 0;color:#8da2c5;font-size:11px;font-weight:650;letter-spacing:.28em;text-transform:uppercase;opacity:0;animation:sv-copy-in .55s 1.05s ease-out forwards}
    .sv-intro__credits{display:grid;gap:5px;margin:18px 0 0;padding:0;list-style:none;color:#aab8d0;font-size:12px;line-height:1.45;text-align:center;opacity:0;animation:sv-copy-in .55s 1.25s ease-out forwards}
    .sv-intro__skip{position:absolute;right:24px;bottom:22px;padding:9px 13px;border:1px solid #a6b8d433;border-radius:999px;background:#0a1020aa;color:#aab8d0;font-family:inherit;font-size:11px;font-weight:600;letter-spacing:.08em;cursor:pointer;transition:color .2s,border-color .2s}
    .sv-intro__skip:hover,.sv-intro__skip:focus-visible{color:#fff;border-color:#42e8ff;outline:none}
    @keyframes sv-mark-in{0%{opacity:0;transform:scale(.72) rotate(-12deg);filter:blur(12px) drop-shadow(0 0 0 #42e8ff00)}65%{opacity:1;transform:scale(1.06) rotate(2deg)}100%{opacity:1;transform:scale(1) rotate(0);filter:drop-shadow(0 0 24px #42e8ff55)}}
    @keyframes sv-copy-in{to{opacity:1}}@keyframes sv-rule-in{to{width:min(42vw,330px)}}
    @keyframes sv-title-in{to{opacity:1;transform:translateY(0)}}
    @keyframes sv-halo{0%{opacity:0;transform:scale(.65)}35%{opacity:1}100%{opacity:.6;transform:scale(1.12)}}
    @keyframes sv-grid{0%{opacity:0;transform:perspective(420px) rotateX(58deg) scale(1.8) translateY(8%)}100%{opacity:.22;transform:perspective(420px) rotateX(58deg) scale(1.5) translateY(0)}}
    @media(prefers-reduced-motion:reduce){.sv-intro,.sv-intro *{animation:none!important;transition:none!important}.sv-intro__rule{width:min(42vw,330px)}.sv-intro__title,.sv-intro__brand,.sv-intro__tag{opacity:1;transform:none}}
  `;

  function play(options) {
    options = options || {};
    const duration = Math.max(1800, Math.min(Number(options.duration) || 5200, 12000));
    const title = String(options.gameTitle || 'Ein neues Abenteuer').slice(0, 80);
    const host = document.createElement('div');
    host.className = 'sv-intro';
    host.setAttribute('role', 'dialog');
    host.setAttribute('aria-label', 'Streamiov Spiele-Intro');
    host.innerHTML = '<div class="sv-intro__grid" aria-hidden="true"></div><div class="sv-intro__halo" aria-hidden="true"></div><div class="sv-intro__content">' + mark + '<div class="sv-intro__brand">STREAMIOV</div><div class="sv-intro__rule"></div><h1 class="sv-intro__title"></h1><div class="sv-intro__tag"></div><ul class="sv-intro__credits"></ul></div><button class="sv-intro__skip" type="button">Überspringen&nbsp; · &nbsp;Enter</button>';
    host.querySelector('.sv-intro__title').textContent = title;
    const isOutro = options.kind === 'outro';
    host.querySelector('.sv-intro__tag').textContent = isOutro ? 'DANKE FÜRS SPIELEN' : 'A STREAMIOV ORIGINAL';
    const credits = Array.isArray(options.credits) ? options.credits.slice(0, 8) : [];
    const creditList = host.querySelector('.sv-intro__credits');
    credits.forEach(function (line) {
      const item = document.createElement('li');
      item.textContent = String(line).slice(0, 120);
      creditList.appendChild(item);
    });
    if (!isOutro || credits.length === 0) creditList.remove();
    const style = document.createElement('style');
    style.textContent = css;
    document.head.appendChild(style);
    document.body.appendChild(host);

    let finished = false;
    let timer;
    function finish() {
      if (finished) return;
      finished = true;
      clearTimeout(timer);
      window.removeEventListener('keydown', onKey);
      host.classList.add('is-leaving');
      window.setTimeout(function () {
        host.remove();
        style.remove();
        if (typeof options.onComplete === 'function') options.onComplete();
      }, 680);
    }
    function onKey(event) {
      if (event.key === 'Enter' || event.key === 'Escape' || event.key === ' ') {
        event.preventDefault();
        event.stopPropagation();
        finish();
      }
    }
    host.querySelector('.sv-intro__skip').addEventListener('click', finish);
    window.addEventListener('keydown', onKey);
    timer = window.setTimeout(finish, duration);
    return { skip: finish };
  }

  root.StreamiovGameBranding = Object.freeze({
    play: play,
    playIntro: function (options) { return play(Object.assign({}, options, { kind: 'intro' })); },
    playOutro: function (options) { return play(Object.assign({}, options, { kind: 'outro' })); }
  });
})(window);
