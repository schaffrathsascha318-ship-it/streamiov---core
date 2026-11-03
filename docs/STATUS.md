# StreamioV status

**Snapshot:** 2026-11-03  
**Scope:** honest status of the repository, not a claim that externally gated features are complete.

## Verified in this checkout

| Area | Evidence |
| --- | --- |
| Local host | `tests/test_streamiov_host.py`: static site, directory indexes, link integrity, accounts, TLS gate, AI-task placeholder |
| Raw-data catalog | `tests/test_data_store.py`, `tests/test_streamiov_host.py`: 18 gifts, 2 games, 3 actions, 1 playlist, 5 templates seeded into a separate read-only SQLite catalog; legacy `data/db` databases untouched |
| Studio source | `tests/test_studio_scene_ui.py`, `tests/test_studio_js_syntax.py`: Electron entry points, inline scripts, scene model, UI wiring |
| Scene renderer | Preview, program, and stream output all call `drawSceneToCanvas`; source layout persists in scene v2 |
| Local tools | Chat, TTS, gifts, alerts, music, games list, AI login/submit, and diagnostics are wired; gift/game/music panels load the host's read-only raw-data catalog; local-only boundaries are stated in the UI |
| Download package | Seven parts with fixed sizes and per-part SHA-256; archive SHA-256 is shown on the page and in `SHA256SUMS.txt` |
| AI worker | `node --test tests/test_cloudflare_ai_worker.mjs` (10 tests) |
| Music rights | `tests/test_music_library.py`, `tests/test_music_research.py` |
| Games | `tests/test_game_*.py` package, catalog, preflight, and AI checks |
| Agent | `tests/test_phase1_agent.py`, `tests/test_agent_response_parsing.py`, `tests/test_coordinator.py` |

Run everything:

```sh
python3 -m unittest discover -s tests -p 'test_*.py'
node --test tests/test_cloudflare_ai_worker.mjs
```

## Built, but not verified on real target hardware

- Windows x64, Linux x64, and Linux ARM64 installers were built on 2026-11-02 and published. Clean-install and first-launch behaviour on each target device is not verified here.
- The RTMP path requires a separately installed FFmpeg with `libx264`, AAC, and RTMP support. A local encoder start is not proof that a streaming service received or published the broadcast.
- Camera, screen, and microphone capture use real Chromium media APIs, but this environment cannot prove behaviour on every camera, capture card, or operating system.
- The 2026-11-03 source snapshot is newer than the published installers. It is source code, not an installer.

## Externally gated

- **TikTok:** app review, approved scopes, and any official gift-event or gift-sending capability. No approval is claimed.
- **Live broadcast:** a real stream received and published by TikTok, YouTube, Twitch, or another service.
- **Mobile:** a tested Android or iOS build. The unlinked stale APK was removed from the public download directory.
- **ChromeOS:** install and start behaviour on real Chromebook hardware.
- **Local model:** inference on a machine with enough memory for the selected model. The current host has about 213 MiB available RAM, which is not enough for the intended model.
- **Code signing:** Windows/macOS signing certificates and notarisation.
- **Public hosting:** an owner-controlled, continuously reachable host with a trusted certificate.
- **Legal review:** music rights, privacy, and platform terms for a public release.

## Known limitations

- The optional Python `modules/` tree is incomplete and is not bundled in the Electron package. Affected handlers return `not_bundled`.
- The host AI task route is a fail-closed placeholder (`503 ai_execution_not_ready`), not an executor.
- Music playback is local only and is not mixed into the stream output. The UI states that rights are the user's responsibility. The music catalog is read-only seed data; the rights catalog is currently empty, and the one test track is marked `test-only`.
- The game list in Studio is informational and comes from the read-only raw-data catalog; prototypes are not installed or launched from Studio.
- The raw-data catalog is seeded only from repository JSON. It has no write API, contains no TikTok gift IDs, and never reads the legacy `data/db` account databases.
- StreamioV-native gifts are free local effects. TikTok gifts remain in TikTok's own purchase and reward systems.
- The old `dist/streamiov-homepage` copy is not used by the host; the complete site is `dist/streamiov-homepage-worker/public`.
- The Studio declares no runtime npm dependencies. The unofficial `tiktok-live-connector` package was removed; any TikTok integration must use an officially approved interface.
- The public community forum is a prepared UI only. `/api/forum/threads` is not implemented, so the page keeps its form disabled and says that the server connection is missing. A real forum needs an authenticated server-side store, moderation, abuse reporting, data-retention rules, and spam controls; it is not part of the local read-only catalog.
- Password recovery by email is not implemented. The operator can create or reset a local account with the host CLI; there is no email delivery service.
- The source snapshot is a point-in-time copy. Its internal `combine.js` and download page can name the checksums of the immediately preceding archive, because editing them changes the archive that contains them. The live site under `dist/streamiov-homepage-worker/public/download/` is authoritative for the published parts; `tests/test_studio_js_syntax.py` verifies those live files byte-for-byte.

## Publication rule

Do not describe a platform as connected, a broadcast as live, or a feature as verified unless the real integration has been exercised. Do not claim TikTok approval, payout values, or device support without evidence.
