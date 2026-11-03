# StreamioV games

Each independently startable game lives in its own project directory under `games/releases/`. Keep game-specific identity while reusing StreamioV's branded title/credits treatment. Every project carries a `manifest.json`, auditable provenance notes, a reproducible build/test command, and a versioned package with a SHA-256 sidecar. The manifest lists every packaged source file and its embedded copy so a checked archive cannot silently drift from the project tree or carry unlisted files.

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
