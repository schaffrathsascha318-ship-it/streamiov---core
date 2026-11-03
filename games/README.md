# StreamioV games

STREAMIOV games are independent products. Each game owns its source, manifest, tests, version, readiness state and release history. A game must never require another game to be installed or running.

Each independently startable game lives in its own project directory. Games packaged for the Studio live under `games/<id>/` and are listed in `games/registry.json`; audited release candidates live under `games/releases/<project>/`. Every release project carries a `manifest.json`, auditable provenance notes, a reproducible build/test command, and a versioned package with a SHA-256 sidecar. The manifest lists every packaged source file and its embedded copy so a checked archive cannot silently drift from the project tree or carry unlisted files.

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
| Star Defender | Arcade shooter | Development |
| Signal Weave | Spatial-routing puzzle | Development |

The Studio registry currently lists Neon Relay, Echo Grid, and Pulse Defender. Star Defender and Signal Weave are packaged release candidates under `games/releases/` and are not yet in the Studio registry. Each game is self-contained, uses its own manifest and has no runtime dependencies on another game. These are playable prototypes in development, not approved public releases.

## Project checks

Create a deterministic package and SHA-256 sidecar from the manifest's explicit source list:

```sh
python3 -m games.package games/releases/streamiov-signal-weave/manifest.json
```

An existing, different package requires `--force`; prefer a version bump for release candidates. Run the manifest, provenance, source, package checksum, ZIP integrity, embedded-manifest, exact-file-set, and release-gate check from the repository root:

```sh
python3 -m games.catalog games/releases/streamiov-star-defender/manifest.json
```

The command exits successfully for a structurally valid prototype but reports `release_ready: false`. Use `--require-release` in a release workflow; it fails until tests, gameplay, accessibility, rights, release review, and at least one device-tested platform are recorded as passed. A manifest field is an evidence pointer, not proof by itself: keep test outputs and review records with the project.

The local release directory currently contains five separately packaged prototypes: Star Defender (arcade shooter), Neon Relay (reflex/dodge arcade), Echo Grid (memory sequence puzzle), Pulse Defender (wave shooter), and Signal Weave (spatial-routing puzzle). Each browser game includes the local StreamioV intro and symbol assets, and each manifest targets responsive HD/Full HD layouts. These are genre samples, not proof that every game genre is complete.

All five remain prototypes. HD is a design target only: no local browser viewport run or physical HD/touch device verification is recorded for the three newly imported games. Star Defender has only a development-host Tk display smoke, and Signal Weave has static responsiveness checks. Full gameplay, accessibility, ownership, rights, and release reviews remain open. Do not present these packages as approved public releases.

GitHub issue #3 lists Neon Relay (reflex arcade), Echo Grid (sequence-memory puzzle), and Pulse Defender (wave shooter). Local copies are now packaged and audited through this repository's manifests; upstream Chromium smoke evidence is not substituted for local browser or hardware verification. Signal Weave adds a distinct spatial-routing puzzle. Its SVG/CSS layout is designed to scale through HD/Full HD, while actual HD viewport and touch-device checks remain pending.

## Required per-game files

Every game must include:

- `game.json`: stable ID, version, entry point, controls, supported modes and release status (used by the Studio registry).
- `manifest.json`: release-candidate metadata, source list, provenance and release gates (used by `games.package` / `games.catalog`).
- `index.html` (or a documented native entry point): actual game implementation.
- `README.md`: rules, controls, local run instructions and verification checklist.
- automated tests appropriate to its runtime.

Never mark a game released because its files merely exist or because CI passed.

## Independent game publishing

A game is released separately through the manual GitHub Actions workflow **Publish an independent STREAMIOV game**. Before it can publish, its own manifest must be committed with `status: gameplay_verified` and `release.gameplayVerified: true`, and the operator must explicitly confirm the real-device gameplay checklist. The workflow packages only that game's directory, creates a versioned GitHub Release with SHA-256 checksums, then records the released state in the registry. CI success alone cannot unlock publication.
