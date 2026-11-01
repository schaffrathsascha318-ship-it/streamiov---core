# STREAMIOV Games

STREAMIOV games are independent products. Each game owns its source, manifest, tests, version, readiness state and release history. A game must never require another game to be installed or running.

## Release states
- planned: concept only; not playable and not distributable.
- development: source is being built; not publicly released.
- automated_tests_passed: automated checks pass; human gameplay verification is still required.
- gameplay_verified: a tester has completed the documented gameplay checklist on supported devices.
- released: a versioned public release exists and its download is available.

Automated tests alone never promote a game to gameplay_verified. A game can be released independently once its own release gates pass; the full STREAMIOV ecosystem launch remains a separate decision.

## Initial game collection

| Game | Genre | Status |
|---|---|---|
| Neon Relay | Reflex / collect-and-dodge arcade | Development |
| Echo Grid | Memory / sequence puzzle | Development |
| Pulse Defender | Arcade shooter / wave defence | Development |

Each game is self-contained, uses its own manifest and has no runtime dependencies on another game. These are playable prototypes in development, not approved public releases.

## Required per-game files
Every game must include:
- `game.json`: stable ID, version, entry point, controls, supported modes and release status.
- `index.html` (or a documented native entry point): actual game implementation.
- `README.md`: rules, controls, local run instructions and verification checklist.
- automated tests appropriate to its runtime.

Never mark a game released because its files merely exist or because CI passed.


## Independent game publishing

A game is released separately through the manual GitHub Actions workflow **Publish an independent STREAMIOV game**. Before it can publish, its own manifest must be committed with `status: gameplay_verified` and `release.gameplayVerified: true`, and the operator must explicitly confirm the real-device gameplay checklist. The workflow packages only that game's directory, creates a versioned GitHub Release with SHA-256 checksums, then records the released state in the registry. CI success alone cannot unlock publication.
