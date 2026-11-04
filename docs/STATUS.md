# StreamioV status

**Snapshot:** 2026-11-03  
**Scope:** honest status of the repository, not a claim that externally gated features are complete.

## Verified in this checkout

| Area | Evidence |
| --- | --- |
| Local host | `tests/test_streamiov_host.py`: static site, directory indexes, link integrity, accounts, TLS gate, AI-task placeholder |
| Community forum | `tests/test_forum.py`: public read, session-gated same-origin writes, validation, per-IP rate limits, replies, locking, soft deletes, moderation CLI |
| Raw-data catalog | `tests/test_data_store.py`, `tests/test_streamiov_host.py`: 18 gifts, 2 games, 3 actions, 1 playlist, 5 templates seeded into a separate read-only SQLite catalog; legacy `data/db` databases untouched |
| Studio source | `tests/test_studio_scene_ui.py`, `tests/test_studio_js_syntax.py`: Electron entry points, inline scripts, scene model, UI wiring |
| Schutzregie / Privacy Shield | `engine/privacy-shield.js` and `engine/privacy-shield.test.js`; hotkey switches the program scene to PAUSE and the local mic mix to 0 %, restores both on exit, persists its own restore state, and states that the encoder, recording, and platform privacy are not stopped. Included in the published Studio 1.0.1 installers and in the Web-Regie/PWA. |
| Scene renderer | Preview, program, and stream output all call `drawSceneToCanvas`; source layout persists in scene v2 |
| Local tools | Chat, TTS, gifts, alerts, music, games list, AI login/submit, and diagnostics are wired; gift/game/music panels load the host's read-only raw-data catalog; local-only boundaries are stated in the UI |
| Download hub | `tests/test_streamiov_host.py`: every local download link resolves; Studio 1.0.1 links, source parts, and five game-prototype ZIPs match their SHA-256 files |
| Homepage and promo | `tests/test_streamiov_host.py`: every local homepage and promo link resolves; downloads, forum, account, honest AI/game/music status, real screenshots, and the Schutzregie demo are linked |
| Cloudflare config | `scripts/verify-cloudflare-config.py`, `tests/test_cloudflare_config.py`: assets-only homepage Worker, AI binding, pinned model, bearer auth, deploy script, security headers, and download checksums are consistent offline |
| AI worker | `node --test tests/test_cloudflare_ai_worker.mjs` (12 tests) |
| Cloudflare live inference | On 2026-11-03 the already-deployed AI Worker answered a minimal authenticated request with HTTP 200 and `STREAMIOV_AI_OK` using `@cf/zai-org/glm-4.7-flash`; `python -m ai --doctor` exited 0 with the owner env |
| AI specialists | `tests/test_specialist_registry.py`: all 11 roles, CLI choices, mission/scope text, unique per-role scopes, and enforced write boundaries |
| AI queue and agent | `tests/test_persistent_task_queue.py`, `tests/test_worker_service.py`, `tests/test_phase1_agent.py`, `tests/test_agent_response_parsing.py`, `tests/test_ai_queue_cli.py` |
| Music rights | `tests/test_music_library.py`, `tests/test_music_research.py` |
| Games | `tests/test_game_*.py` package, catalog, preflight, and AI checks; five checksummed prototype ZIPs are published through the download hub |
| Release signatures | `tests/test_release_signing.py`: Ed25519 key generation, signing, verification, tamper detection and `verify-release` against the published key; the private key stays outside the repository |
| Acceptance tooling | `tests/test_stream_audio_check.py`, `tests/test_hardware_report.py`: the local RTMP audio check fails cleanly without FFmpeg and verifies AAC/H.264 recordings when it is present; the hardware report hashes tested installers |

Run everything:

```sh
python3 -m unittest discover -s tests -p 'test_*.py'
node --test tests/test_cloudflare_ai_worker.mjs
python3 scripts/verify-cloudflare-config.py
node scripts/release-signing.mjs verify-release
```

## Cloudflare and GitHub deployment state

- `.github/workflows/cloudflare-checks.yml` verifies the checked-in homepage Worker, AI Worker, deploy script, security headers, and download checksums offline on pull requests and pushes to `main`.
- `.github/workflows/cloudflare-deploy.yml` is a manual, owner-approved workflow. It requires the GitHub `production` environment secrets `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID`. It never runs on push or pull request. The homepage target deploys the `streamiov` Pages project, which serves `streamiov.pages.dev`.
- The AI Worker is already deployed at `https://streamiov-ai-worker.schaffrathsascha318.workers.dev`. Its bearer secret is configured, `python -m ai --doctor` exits 0, and a minimal authenticated inference returned `STREAMIOV_AI_OK` on 2026-11-03. The credentials used for that check live in the owner's local `~/.config/streamiov/ai-worker.env`, not in this repository.
- The static homepage is published to the `streamiov` Pages project. A custom domain is not configured; `streamiov.pages.dev` is the public URL. Each deployment is versioned and can be rolled back in Cloudflare.
- A successful Wrangler command alone is not proof that every asset is publicly reachable. The live URL, the download page, and the checksum files are checked separately after each deployment.
- CI deployment still needs the GitHub environment secrets above. The repository contains no Cloudflare credentials and no bearer token.

## Built, but not verified on real target hardware

- Studio 1.0.1 installers for Windows x64/ARM64 and Linux x64/ARM64 were built and published on 2026-11-03. The Linux-x64 DEB was downloaded, its SHA-256 was verified against `SHA256SUMS.txt`, and its `app.asar` was extracted to confirm version 1.0.1 plus `engine/privacy-shield.js`. Clean-install and first-launch behaviour on each target device is still not verified here.
- The RTMP path requires a separately installed FFmpeg with `libx264`, AAC, and RTMP support. A local encoder start is not proof that a streaming service received or published the broadcast.
- Camera, screen, and microphone capture use real Chromium media APIs, but this environment cannot prove behaviour on every camera, capture card, or operating system.
- The 2026-11-03 source snapshot is source code, not an installer. It excludes credentials, production databases, built installers, caches, binary download artifacts, and the generated download metadata (parts, checksums, `combine.js`, download page). Archive entries use a fixed timestamp, so the same commit produces byte-identical parts and checksums on any machine.
- The Schutzregie / Privacy Shield is local UI state. It switches the program scene to PAUSE and the local microphone mixer to 0 %, then restores both values. It does not stop the encoder or a running recording, and it does not guarantee platform-side privacy. It is included in Studio 1.0.1 and the PWA.

## Externally gated

The per-item acceptance procedure, evidence format, and pass/fail criteria are in
[`docs/operations/external-verification.md`](operations/external-verification.md).
Nothing in this section counts as verified until that checklist is completed with
a dated record.

- **TikTok:** app review, approved scopes, and any official gift-event or gift-sending capability. No approval is claimed.
- **Live broadcast:** a real stream received and published by TikTok, YouTube, Twitch, or another service.
- **Mobile:** a tested Android or iOS build. The unlinked stale APK was removed from the public download directory.
- **ChromeOS:** install and start behaviour on real Chromebook hardware.
- **Local model:** local-only inference on a machine with enough memory for the selected model. The current host has about 213 MiB available RAM, which is not enough for the intended model. Cloudflare inference is available and verified separately.
- **OS code signing:** CA-backed Windows Authenticode and Apple notarisation. The project-level Ed25519 release signature is implemented and published; it proves integrity/origin but does not create SmartScreen or Gatekeeper trust. A trusted CA certificate costs money and is not purchased automatically.
- **Custom domain:** a StreamioV-controlled domain with its own DNS and certificate. The public `streamiov.pages.dev` site is reachable, but a custom domain is not configured.
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
- The public community forum is real but local-first. Threads and replies are stored in a separate `forum.sqlite3`; anyone can read, and writes require a host session, an exact same-origin request, JSON bodies, length validation, and per-IP rate limits. Operators can lock, unlock, and soft-delete entries with the host CLI. It does not yet provide abuse reporting, per-user post history, automatic spam detection, email notifications, or a documented data-retention policy.
- Password recovery by email is not implemented. The operator can create or reset a local account with the host CLI; there is no email delivery service.
- The source snapshot is a point-in-time copy. Because a file cannot contain its own archive checksum, the generated download metadata is not part of the archive; the live site under `dist/streamiov-homepage-worker/public/download/` is authoritative for the published parts and hashes. `tests/test_studio_js_syntax.py` verifies the live files byte-for-byte.

## Publication rule

Do not describe a platform as connected, a broadcast as live, or a feature as verified unless the real integration has been exercised. Do not claim TikTok approval, payout values, or device support without evidence.
