# Streamiov game branding — first draft

This folder contains an original, scalable Streamiov mark and a reusable game intro. The direction follows the current homepage palette: near-black navy, electric cyan, mint, and violet. The signal ring and play mark are drawn as SVG vectors so they stay crisp in desktop, web, and game builds.

## Files

- `streamiov-symbol.svg` — standalone square icon.
- `streamiov-wordmark.svg` — icon with Streamiov wordmark for title screens and credits.
- `streamiov-game-intro.js` — dependency-free, skippable intro and credits outro for browser-based game builds.
- `preview.html` — local visual preview; opens the intro on load.

## Add the intro to a game

Load `streamiov-game-intro.js` and call:

```js
StreamiovGameBranding.play({
  gameTitle: 'NEON RELAY',
  onComplete: startTitleScreen
});
```

For an end screen, call `StreamiovGameBranding.playOutro({ gameTitle, credits, onComplete })`. Pass only verified contributor and asset credits; the module does not invent authorship claims.

The intro closes after about five seconds or can be skipped with Enter, Space, Escape, or the visible button. It honors reduced-motion preferences, uses no network access or external media, and calls `onComplete` after the fade-out. Use the same mark on every Streamiov-original game, followed by that game's own title and credit screen. Keep skip/short-intro controls available so the branding never blocks play.

## Game AI direction

The Game AI can work across genres while each game keeps its own identity under a consistent “A Streamiov Original” credit. Require original designs or documented rights for every code, character, name, font, music, voice, and art asset. Add an intro/outro and accurate credits to each game; a logo or copyright notice by itself does not establish ownership of third-party work.

This is a first visual draft, not a final registered trademark or completed game release.
