# Streamiov

Streamiov is a downloadable desktop studio for streamers. The goal is to give creators one place to prepare a broadcast, manage its sources and scenes, and send it to the streaming service they use.

## Current state

The desktop shell is an Electron app in `dist/streamiov-studio-app/`. Its build workflow targets Windows x64, Linux x64, and Linux ARM64. The Studio currently includes local camera and microphone previews, a persistent scene and source model, system diagnostics, and a synthetic audio/video encoding check.

The current Studio is an early foundation, not a finished live-streaming product. Its platform selector saves a preference but does not sign in to a service. The chat and TTS controls are local demonstrations; gift and alert buttons trigger local, free canvas effects only. Scenes now have a real source list (camera, screen, title card, text) with position, visibility, layer order, and a background colour. The preview monitor, program monitor, and stream encoder use the same canvas renderer, so a user-created layout is what the stream output draws. The media check uses generated test signals, not a creator's full live setup.

The broadcast path encodes the current program scene, including camera, screen, title-card, and text sources, and mixes the chosen microphone/system audio mode to a user-provided RTMP/RTMPS destination. Windows may provide system audio from the selected screen. It currently requires FFmpeg to be installed on the computer with the `libx264` video encoder, AAC audio encoder, and RTMP/RTMPS protocols. FFmpeg is not yet bundled in the downloadable installers. Official platform sign-in is not implemented. Do not treat an RTMP encoder starting as proof that a streaming service received or published the broadcast.

The download page is maintained at `dist/streamiov-homepage-worker/public/download/index.html`. It separates the 2026-11-02 installers from the newer source snapshot, which is checksummed but is not an installer. A successful installer build does not by itself prove that the app can stream or that it works on every device.

The packaged Electron app does not include the optional Python `modules/` tree. Features that need it report `not_bundled` with a clear explanation instead of failing with an import error. The same guard applies in a repository checkout when those optional modules are absent; if they are present, the handlers use them.

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
```

They cover the local host, accounts, the read-only raw-data catalog, AI-worker contract, Studio source and inline-script syntax, scene model, UI wiring, download-part sizes and SHA-256 checksums, music rights, game packaging, and agent behaviour. These are automated checks, not real-device or live-platform evidence.

Still externally gated: TikTok app review/scopes, a real live broadcast received by a streaming service, hardware verification on Windows/Chromebook/Android/iOS, local model inference on a machine with sufficient memory, code signing, public hosting, and legal rights review.

## Build and launch the desktop app

Install Node.js 22.12 or newer and Python 3.10 or newer. From the repository root:

```sh
cd dist/streamiov-studio-app
npm ci
npm start
```

Electron loads `regie-v2.html` directly, so no prestart copy step is required. Creating installers uses the platform-specific scripts in the same package:

```sh
npm run dist:win
npm run dist:linux
npm run dist:linux:arm64
```

Installer builds are also configured in `.github/workflows/studio-build.yml`.

## Repository map

- `dist/streamiov-studio-app/` — Electron desktop app and its installer configuration.
- `dist/streamiov-homepage-worker/public/` — public site, including the download page.
- `data/` — raw JSON seed data for gifts, games, music, overlays, stickers, and game preparation. `data/db/` contains legacy account databases and is never imported by the catalog.
- `host/data_store.py` — read-only SQLite catalog seeded from `data/` JSON; separate from the account database.
- `modules/`, `core/`, `services/`, and `app/` — supporting streaming, device, platform, and service code. Some optional Python modules are incomplete or absent; Studio degrades to `not_bundled` rather than pretending they work.
- `ai/` and `infrastructure/cloudflare/streamiov-ai-worker/` — AI agent foundation and optional model worker.
- `tests/` — automated checks and media pipeline smoke test.

## Development notes

Do not describe a platform as connected, a broadcast as live, or a feature as verified unless the real integration has been exercised. Keep streaming credentials out of source files and logs. Platform-specific sign-in must use the platform's official flow.

