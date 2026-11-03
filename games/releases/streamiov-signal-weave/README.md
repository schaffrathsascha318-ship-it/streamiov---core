# Signal Weave

An original StreamioV spatial logic puzzle. Rotate each pipe tile to route the pulse from source to target through three authored levels. The browser game uses native HTML/CSS/SVG and plain JavaScript; it runs offline and has no server, login, tracking, network call, or third-party runtime package.

## Run

Open `index.html` in a current browser or serve this folder from any static file server. The StreamioV branded intro module is included in `assets/` and needs no network connection.

## Controls and accessibility

- Mouse, touch, Enter, or Space activates a focused pipe tile and rotates it by 90 degrees.
- Tab moves between tiles and controls.
- The start dialog traps interaction until the game begins; progress is announced through a live status region.
- The grid uses vector shapes and responsive CSS, so it stays sharp in HD/Full HD windows and adapts down to touch screens.
- Reduced-motion preferences are honored by the page and shared branded intro.

## Verification and rights

`node --test tests/game.test.cjs` checks all three authored puzzle solutions, initial unsolved states, endpoint locking, reset behavior, local branding, and responsive/touch-ready HTML. `manifest.json` records package provenance and gates. `game.json` follows the shared independent-games entry format.

From the repository root, build a deterministic archive with `python3 -m games.package games/releases/streamiov-signal-weave/manifest.json` and validate it with `python3 -m games.catalog games/releases/streamiov-signal-weave/manifest.json`.

This is a development prototype. Human gameplay, accessibility, and device review remain open. Its source and the adapted StreamioV logo are recorded, but contributor/asset rights review is not complete; the package must not be represented as a released game.
