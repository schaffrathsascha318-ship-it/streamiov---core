# StreamioV status

**Snapshot:** 2026-11-03  
**Scope:** honest status of the repository, not a claim that externally gated features are complete.

## Verified in this checkout

| Area | Evidence |
| --- | --- |
| Local host | `tests/test_streamiov_host.py`: static site, directory indexes, link integrity, accounts, TLS gate, AI-task placeholder, SQLite integrity, schema migration, and degraded health checks |
| Community forum | `tests/test_forum.py`: public read, session-gated same-origin writes, validation, per-IP rate limits, replies, locking, soft deletes, moderation CLI, abuse reports, per-user history, advisory spam signals |
| Raw-data catalog | `tests/test_data_store.py`, `tests/test_streamiov_host.py`: 18 gifts, 2 games, 3 actions, 1 playlist, 5 templates seeded into a separate read-only SQLite catalog; legacy `data/db` databases untouched |
| Studio source | `tests/test_studio_scene_ui.py`, `tests/test_studio_js_syntax.py`, `npm run test:engine`: Electron entry points, inline scripts, scene model, UI wiring, and device-capability report. There is no browser studio, web app, or PWA product. |
| Schutzregie / Privacy Shield | `engine/privacy-shield.js` and `engine/privacy-shield.test.js`; hotkey switches the program scene to PAUSE and the local mic mix to 0 %, restores both on exit, persists its own restore state, and states that the encoder, recording, and platform privacy are not stopped. Included in the installable Studio applications; no PWA or web substitute. |
| Scene renderer | Preview, program, and stream output call `drawSceneToCanvas`; the separate program-output window renders the persisted scene v2 model on its own local canvas; source layout persists in scene v2 |
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

## Chief evidence repair (2026-11-25)

- **Investigated:** the worktree contained pre-existing uncommitted changes in the Chief agent, project tools, mission runner, and tests. The protected autonomous-development workflow and the older night-run project were not touched. Pre-edit copies of the two changed source files are in `backups/chief-protocol-fix-20261125/`.
- **Changed:** `ai/core/agent.py` now separates the tool-protocol examples with a real newline instead of a literal `\n`; `ai/runtime/project_tools.py` now separates `run_python` exit code, stdout, and stderr with real newlines while keeping the uncommitted bubblewrap-only execution policy intact. `tests/test_chief_evidence_format.py` was added with two regression checks for parseable examples and readable sandbox output.
- **Verified locally:** `python3 -m unittest discover -s tests -p 'test_*.py'` ran 333 tests with 0 failures, `node --test tests/test_cloudflare_ai_worker.mjs` passed 12/12, `python3 scripts/verify-cloudflare-config.py` reported 0 errors, and `node scripts/release-signing.mjs verify-release` matched the published key. No deployment or platform approval was performed.
- **Still open:** the pre-existing uncommitted work remains in the worktree; external gates (TikTok review, live broadcast, real-device install, legal review) are unchanged. Next step: make mission retries and test/repair evidence durable so a Chief run can prove each file change and its verification.

## Chief verification allowlist (2026-11-25)

- **Investigated:** the agent's `run_tests` tool accepted only the Python unit command, so a Chief repair loop could not produce observed evidence for the Cloudflare worker, Cloudflare configuration, or release signature checks already documented in this repository. Pre-edit copies are in `backups/chief-test-allowlist-20261125/`.
- **Changed:** `ai/runtime/project_tools.py` now maps four fixed, shell-free command strings to fixed argv lists (Python unit suite, Cloudflare AI worker node tests, Cloudflare config verification, release signature verification). `ai/core/agent.py` documents exactly those four strings in the system prompt and requires an observed exit code and output. `tests/test_chief_test_allowlist.py` covers the mapping, rejection of unknown/shell/altered commands, and real execution of the three fast checks through the tool.
- **Verified locally:** all six new regression tests pass; the three fast checks return `exit_code=0` through `ProjectTools.run_tests`. No shell injection path is added because the model supplies only an exact allowlist key and never argument text.
- **Still open:** the full Python suite remains intentionally excluded from tests-within-tests to avoid recursion; it is run separately from the repository root. No production deployment or release publication occurred. Mission retry bookkeeping was inspected and looked consistent; no further fix was made there.

## Chief retry bookkeeping review (2026-11-25)

- **Investigated:** `ai/runtime/continuous_engine.py` retry and failure bookkeeping. No additional defect was found, so that path was left unchanged.

## Core forum safety (2026-11-25)

- **Investigated:** the documented gap in `host/forum.py`: the real local forum had no abuse reports, no per-user post history, and no spam signals. Pre-edit copies are in `backups/core-forum-safety-20261125/`. The protected workflow, security/OAuth configuration, and existing uncommitted work were not touched; nothing was deployed.
- **Changed:** `host/forum.py` now stores reports in a separate `forum_reports` table with `open/resolved/dismissed` status, reporter and target validation, duplicate-report protection, and a 500-character detail limit. It also stores advisory `spam_flags` from repeated characters, many links, mostly capitals, and recent duplicates. Spam flags never reject or delete posts. `user_history` lists a user's visible threads and replies from both tables.
- **Changed:** `host/server.py` adds `POST /api/forum/reports` and `GET /api/forum/users/<id>/posts`. Reports require a host session, an exact same-origin request, a strict JSON payload, and a separate five-per-ten-minute limit; history requires a session. `/api/status` now exposes `forum_reports_enabled`, `forum_spam_signals_enabled`, and `forum_history_requires_session` without claiming a full forum API.
- **Changed:** the operator CLI adds `--forum-reports`, `--forum-resolve-report ID resolved|dismissed`, `--forum-spam`, and `--forum-history USER_ID`. The forum page now has working report and per-user-post buttons for threads and replies, plus a history panel.
- **Verified locally:** `python3 -m unittest discover -s tests -p 'test_*.py'` ran 349 tests with 0 failures; `node --test tests/test_cloudflare_ai_worker.mjs` passed 12/12; `python3 scripts/verify-cloudflare-config.py` reported 0 errors; `node scripts/release-signing.mjs verify-release` matched the published key; `git diff --check` found no whitespace errors after cleanup.
- **Still open:** report resolution is CLI-only; there is no in-page moderator queue, email notification, or retention policy. Spam scores are advisory only and still need operator review. No production deployment or release publication occurred. Next Studio step was completed: wire `dist/streamiov-studio-app/engine/device-capabilities.js` into `regie-v2.html` and test the compact-layout path.

## Studio device capability wiring (2026-11-25)

- **Investigated:** `dist/streamiov-studio-app/engine/device-capabilities.js` and its Node tests existed, but the canonical Web-Regie/PWA never loaded the module and the generated PWA did not copy or precache it. Pre-edit copies are in `backups/studio-device-capabilities-20261125/`. The protected workflow, security/OAuth configuration, and existing uncommitted work were not touched; nothing was deployed.
- **Changed:** the module now uses the same UMD pattern as the Schutzregie, keeping `module.exports` for Node tests and exposing `window.StreamioVDeviceCapabilities` to classic browser scripts. `FEATURE_KEYS`, all status strings, immutable reports, and the layout-only behaviour are unchanged; unknown features are still `limited` with the explicit reason that no device adapter checked them.
- **Changed:** `regie-v2.html` loads the classic module script, renders a read-only capability/API/layout snapshot in the Geräte tool, and appends a layout hint to runtime diagnostics. The snapshot asks for no device permission, does not gate controls, does not change the scene model, and does not treat API presence or `navigator.userAgent` as a verified capability.
- **Changed:** `scripts/build-mobile-pwa.py` copies the module into the generated PWA; `dist/streamiov-homepage-worker/public/app/sw.js` now uses cache `streamiov-web-regie-v3` and precaches the module. `dist/streamiov-homepage-worker/public/app/index.html` was regenerated, not hand-edited.
- **Verified locally:** `npm run test:engine` passed 37/37 from `dist/streamiov-studio-app`; `python3 -m unittest tests.test_studio_scene_ui tests.test_studio_js_syntax` passed 38 tests; `python3 scripts/test-mobile-pwa.py` passed after regeneration; the full Python suite ran 351 tests with 0 failures; Cloudflare worker tests passed 12/12, config verification reported 0 errors, release signature matched, and `git diff --check` was clean.
- **Still open:** no Electron IPC exposes `process.platform` or `os.arch()`, so platform/architecture remain `unknown`; real camera, screen, microphone, and live broadcast behaviour are still unverified here. No production deployment or release publication occurred. Next step was completed: render the persisted scene through a real canvas in the program-output window.

## Studio program output canvas (2026-11-25)

- **Investigated:** `dist/streamiov-studio-app/program-output.html` was a one-line text placeholder that only showed the scene name and said `VIDEO-COMPOSITOR NOCH NICHT ANGESCHLOSSEN`. The main process pushed scene state only on load, `take`, and `set-program`; the Regie button `openProgramOutput` actually moved Regie to a second display instead of opening the output window. Pre-edit copies are in `backups/studio-program-output-20261125/`. The protected workflow, security/OAuth configuration, and existing uncommitted work were not touched; nothing was deployed.
- **Changed:** `main.js` now has one `publishProgramScene(snapshot)` helper. Every successful persisted scene action publishes the active scene to `studio:program-scene`; the initial output load publishes the full persisted scene snapshot. The output window remains sandboxed and still reports `renderedVideo: false`.
- **Changed:** `program-output.html` now draws the scene on a 1280×720 canvas from the pushed snapshot: background, visible sources in `z` order, title/text cards, and explicit camera/screen placeholders. It sanitizes scene data and uses `fillText`, not HTML injection. The status line explicitly says `LOKALE CANVAS · NOCH KEIN LIVE-VIDEO`; the old compositor claim is gone.
- **Changed:** `regie-v2.html` adds a separate `PROGRAMMAUSGABE FENSTER` button that calls the existing trusted `openProgramOutput()` bridge; the previous second-display Regie button keeps its original meaning. The generated PWA was regenerated and honestly reports that the desktop app is required for the output window.
- **Verified locally:** `npm run test:engine` passed 37/37 from `dist/streamiov-studio-app`; `python3 -m unittest tests.test_studio_scene_ui tests.test_studio_js_syntax` passed 40 tests; `python3 scripts/test-mobile-pwa.py` passed after regeneration; the full Python suite ran 353 tests with 0 failures; Cloudflare worker tests passed 12/12, config verification reported 0 errors, release signature matched, and `git diff --check` was clean.
- **Still open:** this is a local scene canvas, not a live video compositor. Camera and screen sources are placeholders in the output window because real tracks stay in Regie; fades, gifts, alerts, encoder output, devices, platform login, and live publication are not bridged or verified here. No production deployment or release publication occurred.

## Chief retry diagnostics in checkpoints (2026-11-25)

- **Investigated:** `ContinuousDevelopmentEngine` appends the latest failure to a retry prompt, but `DevelopmentAgent.run` stripped that suffix before loading a checkpoint. A resumed Chief task therefore lost the diagnostic even though the engine supplied it; lesson context could also change the checkpoint digest between the first attempt and a retry. Pre-edit copies are in `backups/chief-retry-diagnostic-20261125/`. The protected workflow, security/OAuth configuration, and existing uncommitted work were not touched; nothing was deployed.
- **Changed:** `ai/core/agent.py` now separates the retry diagnostic before lesson-context formatting, so the checkpoint digest stays stable. On resume it adds a single explicit `UNTRUSTED RETRY DIAGNOSTIC` user message, bounded to 4,000 characters, and replaces any older diagnostic message from a previous retry. The diagnostic is labelled as reference-only, not as instructions.
- **Changed:** `tests/test_phase1_agent.py` verifies that the diagnostic appears exactly once across two consecutive retries and survives checkpoint persistence. `tests/test_continuous_engine.py` verifies that a checkpoint-aware retry agent receives the same task ID and the failure text from the engine.
- **Verified locally:** the two focused unittest modules passed 40 tests; the full Python suite ran 355 tests with 0 failures; `python3 -m compileall -q ai tests` and `git diff --check` were clean. No production deployment or release publication occurred.

## Core SQLite integrity and honest health (2026-11-25)

- **Investigated:** `/healthz` always answered `ok`, and `/api/v1/status` hard-coded `auth_ready`, `account_api_ready`, `forum_ready`, and forum feature flags as true regardless of the underlying SQLite files. Legacy forum databases with missing `locked/deleted` columns also broke index creation during startup because indexes were created before schema migration. Pre-edit copies are in `backups/core-sqlite-health-20261125/`. The protected workflow, security/OAuth configuration, and existing uncommitted work were not touched; nothing was deployed.
- **Changed:** `host/server.py` now runs `PRAGMA quick_check(1)` and required-table/column checks for the account, forum, and catalog databases. `/healthz` returns `503` with `status: degraded` and per-store error codes when a store is unavailable or its schema drifts. `/api/v1/status` exposes the same checks and derives `auth_ready`, `account_api_ready`, `catalog_ready`, `forum_ready`, report/spam/history flags, and `data_store.ok` from the observed state instead of claiming readiness unconditionally. Error payloads use stable codes and database filenames, not paths, credentials, or row contents.
- **Changed:** `host/forum.py` migrates legacy `threads.locked`, `threads.deleted`, `replies.deleted`, `forum_reports.resolved_at`, and `forum_reports.resolved_by` columns before creating indexes, so old local databases are upgraded in place without guessing application data.
- **Changed:** `tests/test_streamiov_host.py` verifies healthy checks, a damaged account database producing a degraded `503` healthz response, a damaged forum database removing all ready claims from `/api/v1/status`, and a legacy forum schema gaining the required columns.
- **Verified locally:** the focused host/forum/data-store modules passed 57 tests with `ResourceWarning` promoted to an error; the full Python suite ran 358 tests with 0 failures; `python3 -m compileall -q host tests` and `git diff --check` were clean. No production deployment or release publication occurred.

## Generated PWA drift guard (2026-11-25)

- **Investigated:** `scripts/test-mobile-pwa.py` always called the generator before asserting, so CI could not detect stale committed PWA artifacts. The mobile-PWA workflow therefore regenerated the page during the test and would not fail when the checked-in generated files drifted from the canonical Studio UI. Pre-edit copies are in `backups/studio-pwa-drift-20261125/`. The protected autonomous-development workflow was not touched; nothing was deployed.
- **Changed:** `scripts/build-mobile-pwa.py` gained `--check`, which compares the committed HTML and both copied engine modules with bytes generated from `regie-v2.html`, `privacy-shield.js`, and `device-capabilities.js` without rewriting anything. `scripts/test-mobile-pwa.py` forwards `--check`; its default mode still rebuilds for local development.
- **Changed:** `.github/workflows/mobile-pwa.yml`, `.github/workflows/streamiov-full-checks.yml`, and `.github/workflows/cloudflare-deploy.yml` now verify committed generated artifacts instead of silently rebuilding or deploying them. `tests/test_studio_scene_ui.py` adds the same check to the Python suite, and a temporary drift was confirmed to produce a nonzero exit status with a `Stale generated PWA artifacts` message before the file was restored.
- **Verified locally:** the PWA check passed on the committed artifacts, the focused Studio Python modules passed 41 tests, and the full Python suite ran 359 tests with 0 failures; `python3 -m compileall -q scripts tests` and `git diff --check` were clean. No production deployment or release publication occurred.

## Native-only product correction (2026-11-25)

- **Investigated:** the public site still shipped a generated browser studio under `/app/`, the GitHub release `studio-v1.0.3` still contained a PWA ZIP, and several workflows/docs/tests treated that PWA as a product. The protected autonomous-development workflow and pre-existing uncommitted Chief work were not changed. Pre-edit copies are in `backups/native-only-20261125/`.
- **Changed:** removed `public/app/`, `scripts/build-mobile-pwa.py`, `scripts/test-mobile-pwa.py`, `.github/workflows/mobile-pwa.yml`, PWA steps in Cloudflare/full-check workflows, and the generated-artifact test class. The homepage, download hub, promo page, studio redirect, README, implementation notes, and release notes now describe only installable applications; the offline Cloudflare verifier and test suite now reject a reintroduced browser app.
- **Changed:** `dist/streamiov-studio-app` is version `1.0.4`, with a repeatable Windows ARM64 script, workflow matrix entry, and publish mapping. The release body states that macOS, Android, and iOS remain open until real installable builds and device tests exist.
- **Changed externally:** deleted `Streamiov.Mobile.Regie.1.0.3-PWA.zip` from `studio-v1.0.3`, replaced its `SHA256SUMS.txt` without the PWA hash, and rewrote that release body to remove PWA promotion.
- **Verified locally:** the full Python suite ran 359 tests with 0 failures; `npm run test:engine` passed 37/37; `node --test tests/test_cloudflare_ai_worker.mjs` passed 12/12; `python3 scripts/verify-cloudflare-config.py` reported 0 errors; `node scripts/release-signing.mjs verify-release` matched the published key; `git diff --check` was clean.
- **Still open:** the `studio-v1.0.4` workflow has not yet been published and the public site has not been redeployed in this step. Native macOS, Android, iOS, and full ChromeOS device verification remain open.

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
- The Schutzregie / Privacy Shield is local UI state. It switches the program scene to PAUSE and the local microphone mixer to 0 %, then restores both values. It does not stop the encoder or a running recording, and it does not guarantee platform-side privacy. It is included in the installable Studio applications; it is not offered as a web or PWA feature.

## Externally gated

The per-item acceptance procedure, evidence format, and pass/fail criteria are in
[`docs/operations/external-verification.md`](operations/external-verification.md).
Nothing in this section counts as verified until that checklist is completed with
a dated record.

- **TikTok:** app review, approved scopes, and any official gift-event or gift-sending capability. No approval is claimed.
- **Live broadcast:** a real stream received and published by TikTok, YouTube, Twitch, or another service.
- **Mobile:** tested, installable Android and iOS applications. No browser app or PWA counts as a substitute; no tested native mobile build is available yet.
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
- The Regie device-capability module reports API presence and presentation density only. Platform/architecture stay `unknown` because no Electron bridge exposes them, and no real capture device is verified here.
- The external program-output window renders a local scene canvas, not live video. Camera/screen sources are placeholders there; effects, encoder output, devices, platform login, and live publication are not bridged into that window.
- The raw-data catalog is seeded only from repository JSON. It has no write API, contains no TikTok gift IDs, and never reads the legacy `data/db` account databases.
- StreamioV-native gifts are free local effects. TikTok gifts remain in TikTok's own purchase and reward systems.
- The old `dist/streamiov-homepage` copy is not used by the host; the complete site is `dist/streamiov-homepage-worker/public`.
- The Studio declares no runtime npm dependencies. The unofficial `tiktok-live-connector` package was removed; any TikTok integration must use an officially approved interface.
- The public community forum is real but local-first. Threads, replies, abuse reports, and advisory spam flags are stored in a separate `forum.sqlite3`; anyone can read threads and replies, and writes require a host session, an exact same-origin request, JSON bodies, length validation, and per-IP rate limits. Reports and history are session-gated; spam flags are advisory only and never reject or delete posts. Operators can lock, unlock, soft-delete entries, list/history reports, and resolve or dismiss reports with the host CLI. It does not yet provide an in-page moderator queue, email notifications, or a documented data-retention policy.
- Password recovery by email is not implemented. The operator can create or reset a local account with the host CLI; there is no email delivery service.
- The source snapshot is a point-in-time copy. Because a file cannot contain its own archive checksum, the generated download metadata is not part of the archive; the live site under `dist/streamiov-homepage-worker/public/download/` is authoritative for the published parts and hashes. `tests/test_studio_js_syntax.py` verifies the live files byte-for-byte.

## Publication rule

Do not describe a platform as connected, a broadcast as live, or a feature as verified unless the real integration has been exercised. Do not claim TikTok approval, payout values, or device support without evidence.
