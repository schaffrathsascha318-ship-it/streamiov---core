# Streamiov

Streamiov is a downloadable desktop studio for streamers. The goal is to give creators one place to prepare a broadcast, manage its sources and scenes, and send it to the streaming service they use.

**Von Streamern für Streamer. Zum Nulltarif.**

StreamioV bleibt dauerhaft kostenlos: keine Abos, Pro-Stufen, Werbung, Verkäufe oder Zahlungspflicht – ein kostenloses Angebot für alle.

## Current state

The desktop shell is an Electron app in `dist/streamiov-studio-app/`. Its build workflow targets Windows x64/ARM64, Linux x64/ARM64, and ChromeOS x64/ARM64 via Crostini; macOS, Android, and iOS need their own installable applications. There is no browser studio and no PWA substitute. **StreamioV Studio 1.0.1** was published on 2026-11-03. The Studio includes local camera and microphone previews, a persistent scene and source model, system diagnostics, and a synthetic audio/video encoding check. It also includes the **Schutzregie / Privacy Shield**: `Ctrl+Shift+P` requests a stop of the active local encoder and recording, switches the program to PAUSE and the local microphone mix to 0 %, then restores only the scene and microphone values when deactivated. The broadcast is not resumed automatically; a failed stop must be checked manually and platform-side privacy is not guaranteed. The installable Studio applications contain the shield.

The current Studio is an early foundation, not a finished live-streaming product. Its platform selector saves a preference but does not sign in to a service. The chat and TTS controls are local demonstrations; gift and alert buttons trigger local, free canvas effects only. Scenes now have a real source list (camera, screen, title card, text) with position, visibility, layer order, and a background colour. The preview monitor, program monitor, and stream encoder use the same canvas renderer, so a user-created layout is what the stream output draws. The media check uses generated test signals, not a creator's full live setup.

The broadcast path encodes the current program scene, including camera, screen, title-card, and text sources, and mixes the chosen microphone/system audio mode to a user-provided RTMP/RTMPS destination. Windows may provide system audio from the selected screen. It currently requires FFmpeg to be installed on the computer with the `libx264` video encoder, AAC audio encoder, and RTMP/RTMPS protocols. FFmpeg is not yet bundled in the downloadable installers. Official platform sign-in is not implemented. Do not treat an RTMP encoder starting as proof that a streaming service received or published the broadcast.

The download page is maintained at `dist/streamiov-homepage-worker/public/download/index.html`. It centralizes the Studio installers for Windows x64/ARM64 and Linux x64/ARM64, the newer source snapshot (checksummed, but not an installer), the status of native mobile and ChromeOS applications, account/forum links, and five checksummed game prototypes. No web app or PWA is offered. The promo page at `dist/streamiov-homepage-worker/public/promo/index.html` contains real screenshots and a frame-captured Schutzregie demo, ready-to-copy social text, and the same honest limits. The prototypes are development builds, not releases. A successful installer build does not by itself prove that the app can stream or that it works on every device.

The packaged Electron app does not include the optional Python `modules/` tree. Studio does not invoke it: affected capability handlers report `not_implemented` or `dependency_gated` with a clear explanation instead of failing with an import error or claiming a working native pipeline.

The local host also builds a **read-only catalog** from the JSON files under `data/` (`game_actions/`, `music/`, `overlays/`, `stickers/`, and game preparation specs). It stores that catalog in its own SQLite database under the host data directory and never opens the legacy `data/db/*.sqlite3` account databases. The Studio gift, game, and music panels load this catalog from the host. The catalog contains 18 free StreamioV gift previews, 2 locally registered test games, 3 test actions, 1 test playlist, and 5 local template specifications. It contains no TikTok gift IDs, no purchased gifts, and no platform credentials.

## Product milestones

1. **Reliable downloadable app** — make a clean install and first launch work on each advertised operating system, bundle the media encoder with license notices/source where required, show useful setup guidance, and publish versioned installers.
2. **First real broadcast** — capture creator-selected sources, compose a real program output, and stream it to a user-provided RTMP destination with clear connection and stop controls. The current camera/screen and microphone path is an initial step; it still depends on a separately installed encoder and needs end-to-end verification.
3. **Streamer workflow** — save profiles and scenes, add practical source and audio controls, and recover cleanly from device or network interruptions.
4. **Platform integrations** — add official sign-in and platform features where supported. Keep generic RTMP available for services that accept a stream URL and key.
5. **Release readiness** — document supported hardware and platform limits, verify install and broadcast workflows on the advertised systems, and keep download links aligned with each release.

## Verified locally

See [`docs/STATUS.md`](docs/STATUS.md) for the full built/verified/blocked matrix. The following checks pass in this checkout:

```sh
python3 -m unittest discover -s tests -p 'test_*.py'
node --test tests/test_cloudflare_ai_worker.mjs
python3 scripts/verify-cloudflare-config.py
node scripts/release-signing.mjs verify-release
```

They cover the local host, accounts, the read-only raw-data catalog, the 11 AI specialist roles and task queue, AI-worker contract, Studio source and inline-script syntax, scene model, UI wiring, download-part sizes and SHA-256 checksums, game-prototype checksums, Ed25519 release signatures, music rights, game packaging, and agent behaviour. These are automated checks, not real-device or live-platform evidence.

For the external checks, use [`docs/operations/external-verification.md`](docs/operations/external-verification.md), `scripts/stream-audio-check.py` (local RTMP audio proof, no purchase needed) and `scripts/collect-hardware-report.py` (per-device evidence report).

Cloudflare and GitHub automation is split into a read-only check workflow (`.github/workflows/cloudflare-checks.yml`) and a trusted, manual owner-approved deployment workflow (`.github/workflows/cloudflare-deploy.yml`). Merging code or pushing to `main` does not deploy production. An owner must manually dispatch the workflow and confirm the target. The deployment workflow requires the `production` environment secrets `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID`; the AI Worker additionally needs the Cloudflare secret `STREAMIOV_AI_WORKER_TOKEN` and an enabled Workers AI binding.

The static site is published to the `streamiov` Pages project at `https://streamiov.pages.dev/`. The AI Worker is deployed at `https://streamiov-ai-worker.schaffrathsascha318.workers.dev`; on 2026-11-03 `python -m ai --doctor` exited 0 and a minimal authenticated inference returned `STREAMIOV_AI_OK`. Those credentials live in the owner's local environment, not in this repository.

Still externally gated: TikTok app review/scopes, a real live broadcast received by a streaming service, hardware verification on Windows/Chromebook/Android/iOS, local model inference on a machine with sufficient memory, CA-backed OS code signing (the free Ed25519 release signature is implemented), and legal rights review.

## Chromebook first launch (Crostini)

For the Chromebook development environment, run the one-time setup and launch helper from the repository root:

```bash
bash scripts/setup-studio-crostini.sh
```

The helper checks Node.js 22.12+, installs the free Debian FFmpeg package only when FFmpeg is absent, verifies that FFmpeg exposes `libx264`, AAC and RTMP, installs the exact locked Electron dependencies with `npm ci`, runs the Studio engine tests, and then starts the local Electron Studio with Crostini-friendly GPU flags. It does not configure Cloudflare, change production services, access credentials, or install a server. If FFmpeg exists but lacks a required codec/protocol, the helper stops and explains what is missing rather than replacing the existing installation.

This prepares the local Studio runtime; it does not prove camera/audio hardware works on the Chromebook or that a remote platform accepts a stream. The app still needs a valid RTMP destination, and platform LIVE verification remains a separate step.

## Build and launch the desktop app

Install Node.js 22.12 or newer and Python 3.10 or newer. From the repository root:

```sh
cd dist/streamiov-studio-app
npm ci
npm start
```

Electron loads `regie-v2.html` directly, so no UI copy step is required. The npm scripts still use Python to sync the packaged game library and the canonical TikTok OAuth service before launch and packaging. Creating installers uses the platform-specific scripts in the same package:

```sh
npm run dist:win
npm run dist:linux
npm run dist:linux:arm64
```

Installer builds are configured in `.github/workflows/studio-build.yml`. Verified changes to the Studio app trigger platform builds. Publishing a versioned GitHub Release is a separate manual owner-approved workflow dispatch and only proceeds after all platform builds and the media-pipeline smoke test pass; the requested release version must match `package.json`.

## AI Chief and project administration

The AI Chief owns technical planning and implementation across the specialist team. Jason is the separate project administrator: it reports project areas, persistent mission progress, specialist queue assignments, and visible blockers without replacing the Chief or changing production state.

From the repository root, inspect the current project overview with:

```bash
python3 -m ai --jason-status
```

Jason reads the mission database at `.streamiov/ai-missions.sqlite3` and the specialist queue at `.streamiov/specialist-queue.sqlite3` in read-only mode. Missing databases are reported as unavailable; Jason does not invent progress or create runtime state.

## Repository map

- `dist/streamiov-studio-app/` — Electron desktop app and its installer configuration.
- `dist/streamiov-homepage-worker/public/` — public site, including the download page.
- `data/` — raw JSON seed data for gifts, games, music, overlays, stickers, and game preparation. `data/db/` contains legacy account databases and is never imported by the catalog.
- `host/data_store.py` — read-only SQLite catalog seeded from `data/` JSON; separate from the account database.
- `modules/`, `core/`, `services/`, and `app/` — supporting streaming, device, platform, and service code. Some optional Python modules are incomplete or absent; Studio reports the affected capability as `not_implemented` or `dependency_gated` rather than pretending it works.
- `ai/` and `infrastructure/cloudflare/streamiov-ai-worker/` — AI agent foundation and optional model worker.
- `tests/` — automated checks and media pipeline smoke test.

## Projektbereiche

- **Studio:** Electron-Desktop-Regie und Geräte-/Medienintegration.
- **Mobile und Chromebook:** eigenständige installierbare Anwendungen für Android, iPhone/iPad und ChromeOS, soweit die Plattform es unterstützt; keine Web-App und keine PWA als Ersatz.
- **Core:** Plattformdienste, sichere Konten und Cloud-Anbindung.
- **Geschenke:** STREAMIOV-native Geschenklogik und getrennte Ledger-Basis.
- **Spiele:** Download und Präsentation ausschließlich auf der offiziellen Homepage; Studio mit automatischer Prozesserkennung, Gameplay-Bildanalyse, Situationserkennung, lokaler Gaming-KI, Statistiken, Fortschritt, Highlight-/Replay-Markierung, Replay-Import, Sprachbefehlen und Chat-/LIVE-Integration; keine Browser-Spiele, keine Spiele-Galerie oder Spiele-Downloads im Studio.

## Verbindliche Statusregeln

Ein grüner Build beweist nur, dass der Build erfolgreich war. Er beweist nicht automatisch, dass ein Paket auf echter Hardware installiert wurde, dass Mediengeräte funktionieren oder dass ein Live-Stream produktiv läuft. Solche Abnahmen werden separat dokumentiert.

Eine PWA ist keine native Android-APK, iOS-App oder Desktop-Anwendung und wird nicht als Ersatz angeboten. Ein TikTok-Sandbox-OAuth-Test ist keine echte TikTok-Autorisierung. Ein Geschenk-Ledger ist keine Zahlungsanbieter- oder Auszahlungslösung.

Keine Zugangsdaten, Tokens oder privaten Schlüssel in Issues, Commits oder Chatnachrichten einfügen.

## Development notes

Do not describe a platform as connected, a broadcast as live, or a feature as verified unless the real integration has been exercised. Keep streaming credentials out of source files and logs. Platform-specific sign-in must use the platform's official flow.

## Sicherheit und Laufzeitdaten

Lokale Secrets, Token-Dateien, Wunschbox-Anfragen, Laufzeitprotokolle und PID-Dateien gehören nicht in das öffentliche Repository. Die Ignore-Regeln sind dafür eingerichtet. Bereits historisch eingecheckte Geheimnisse müssen unabhängig davon widerrufen/rotiert und ihre Historie gesondert bereinigt werden.

## Gesamtprojekt und Abnahme

Der verbindliche Fertigstellungs- und Abnahmestand wird in
[Issue #3](https://github.com/schaffrathsascha318-ship-it/streamiov---core/issues/3) geführt.
Die verbleibenden Integrations- und Sicherheitsarbeiten sind dort einzeln dokumentiert.
