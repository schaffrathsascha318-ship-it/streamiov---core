# StreamioV implementation sequence

This sequence combines the GitHub [`DEVELOPMENT_ROADMAP.md`](DEVELOPMENT_ROADMAP.md) with the owner's zero-spend, self-built-product, music, game-branding, TikTok-login, and TikTok-gift-gallery requirements. It is a work plan, not a claim that listed features are already complete.

The owner's later no-revenue decision supersedes any earlier roadmap language about paid STREAMIOV gifts, payment ledgers, commissions, or payouts. StreamioV-native gifts are free effects only; TikTok-native gifting stays entirely in TikTok's own purchase and reward systems.

## Non-negotiable product constraints

- StreamioV earns no revenue: no ads, subscriptions, paid tiers, sales, donations to StreamioV, paid gifts, commission, or payment collection. Core use requires no purchase. No paid APIs, models, hosting, codecs, music services, commercial SDKs, payment services, or paid fallback may be mandatory.
- StreamioV builds its own product logic: Studio/Regie, scene and media system, local music library and rights registry, games framework, and bounded AI specialists. Local open-source components may be used after license review; their hosted vendors must not be required.
- Use already-owned hardware for local AI and any self-hosted persistent service. A machine that is powered off cannot serve remote requests. A static homepage cannot host a persistent worker or backend.
- GitHub Pages is limited to static project information/downloads, and GitHub Actions to bounded CI/build jobs; neither is the persistent StreamioV server. Actions quotas depend on repository visibility and plan, so guard against billable overages.
- Keep TikTok as an explicit external platform integration, using only official, approved interfaces. Its availability, developer review, granted scopes, account eligibility, and any provider-side requirements are separate from StreamioV-owned software.
- Target Windows, Linux, ChromeOS, Android, and iOS from one shared product core, with device-specific builds and capture/authentication adapters. Design responsive layouts for phones, tablets, Chromebook screens, and desktop displays; verify each target on real hardware before marking it supported.
- Never overwrite existing working-tree changes, creator connections, OAuth configuration, tokens, or production data as routine development.
- Planned, mock, built, and verified states must remain distinct in code, UI, downloads, and public claims.

## Work sequence

### 0. Preserve and reconcile the working baseline

- Record the current branch, clean/dirty state, existing user edits, and base commit before changing implementation code.
- Compare the local checkout to GitHub `main` without replacing the current working tree.
- Inventory all open/closed issues and pull requests and reconcile them with tracker issue #3 and the masterplan.
- Review the local Studio streaming edits as user work; preserve them and separately verify architecture, safe handling of stream credentials, and release status.

**Acceptance:** a written inventory links every major requirement to existing code, open work, blockers, and evidence; no user edits are lost.

### 1. Product cost and provider audit

- Inventory runtime dependencies, model providers, hosting, build tools, media codecs, music inputs, and account/login; verify that no StreamioV payment, ad, sales, or monetization path is introduced.
- Mark each item as local/open-source, owner-provided, external platform, optional free integration, or paid/unknown.
- Remove mandatory paid/vendor-hosted paths from the core; reject unknown license or charge conditions until resolved.
- Make local mode the default and fail closed when a free quota, local model, or host is unavailable.

**Acceptance:** published cost/dependency inventory; fresh setup and core Studio use add no required purchases or subscriptions.

### 2. Own Studio and downloadable Regie

- Build toward a self-contained desktop download with scene collection, preview/program, transitions, sources, local camera/screen capture, audio mixer/routing, media playback, status, and diagnostics.
- Keep Windows, Linux, ChromeOS, Android, and iOS as product targets. Use desktop installers where appropriate and a mobile-friendly/native delivery path per operating system; do not claim that one web build automatically provides full feature parity on every device.
- Own the Regie and stream lifecycle. Do not require OBS, a paid relay, cloud encoder, hosted login, or plugin marketplace.
- Package legally redistributable local media/codec components where possible; document optional system prerequisites and unsupported hardware honestly.
- Keep RTMP-style destinations an advanced adapter only if needed; the intended creator flow is sign-in, connect an eligible TikTok account, and go live through approved means without forcing server/RTMP setup.

**Acceptance:** supported installer starts on a clean supported device, camera/audio/capture and preview are hardware-verified, and every claimed live path is separately authorized and tested.

### 3. TikTok login and gift gallery

- Implement TikTok Login Kit as an optional account-linking method after maintaining a separate StreamioV account/login path where appropriate.
- Use authorization code + PKCE and exact registered redirect URIs; exchange credentials server-side and request only approved, necessary scopes. Do not put client secrets or long-lived tokens in the desktop renderer or public website.
- Preserve existing creator sessions and OAuth configuration. Do not rotate or invalidate credentials without an explicit, tested migration plan.
- Build the gift gallery with two clearly separate catalogues: TikTok-native gift data that an approved official interface actually makes available, and StreamioV-native gifts created by StreamioV. A selected TikTok gift must use TikTok's own approved gifting flow; do not build a StreamioV checkout or imply that StreamioV can send gifts or observe live gift events unless that exact capability is officially granted and verified.
- StreamioV-native gifts are free visual/event actions only. StreamioV does not sell/settle gifts, collect money, take a commission, or process payouts. TikTok-native gifts remain transactions handled by TikTok.
- StreamioV takes no share and handles no TikTok payment or payout. The creator's balance and any withdrawal/reward are governed by TikTok's Diamonds/Virtual Items rules, eligibility, region, and payout terms. Do not promise that a TikTok gift's purchase price converts 1:1 to cash for the streamer.
- Handle denial, revocation, expired tokens, rate limits, unavailable scopes, and review rejection without blocking local Studio use.
- TikTok app review and permissions are an external prerequisite; do not claim approval in code or copy without evidence.

Official reference points: [TikTok Login Kit](https://developers.tiktok.com/products/login-kit/), [TikTok scopes](https://developers.tiktok.com/docs/en/scopes-overview), [TikTok app review FAQ](https://developers.tiktok.com/docs/en/getting-started-faq), and TikTok Support's [Diamonds information](https://support.tiktok.com/en/business-and-creator/video-gifts-on-tiktok/diamonds). TikTok describes Diamonds as virtual items and says rewards eligibility is conditional. Public developer docs confirm Login Kit and scope-based user access; they do not by themselves prove that a live gift-event or gift-sending API is approved for StreamioV. Treat both as gated until the exact official capability and account approval are verified.

**Acceptance:** sandbox/approved-account login works with least-privilege scopes; tokens stay server-side/encrypted; account disconnect works; gallery only shows evidence-backed fields; no existing creator connection is lost.

### 4. Local music player and rights-research AI

- Build a local-file music library and player first; do not copy, scrape, or proxy commercial catalogue audio.
- Store rights evidence per territory and use (local playback, live broadcast, saved VOD/download), with source, date, attribution, permission, and review status.
- Separate legal/rights status from content labels such as explicit sexual material, violence, hate, and political content. Apply conduct policies consistently across political viewpoints; ambiguous classifications are flagged for human review.
- Only allow tracks with documented rights for the selected use; unknown rights remain blocked. The AI researches and summarizes evidence but does not issue legal clearance.

**Acceptance:** tests show unauthorized/unknown tracks cannot be published or selected for restricted use and that permitted local creator tracks can be played without a network service.

### 5. Genre-wide Game AI and StreamioV game identity

- Extend the role-based Game AI to plan, build, balance, and review games across genres using a shared local model when feasible.
- Keep game code and assets original or rights-cleared, with a provenance record for concept, code, art, fonts, audio, and dependencies.
- Reuse the StreamioV mark, skippable intro/outro, game title, and accurate credits. Give every game its own identity beneath the shared “A StreamioV Original” presentation.
- Add build/test and real gameplay review for each genre; never treat a prototype or generated asset as a finished release.

**Acceptance:** multiple independently startable games from distinct genres pass their own build, rights, accessibility, and gameplay gates.

### 6. Local AI specialists and bounded autonomy

- Use domain-specialist roles for code, Studio, games, design, music/rights research, gifts, tests, repair, integration, and operations, sharing one local model where hardware allows.
- Keep task plans bounded by scope, file permissions, timeouts, retry limits, and logs. Work in isolated branches/workspaces and require human approval for financial, destructive, or otherwise unapproved external actions. The owner has explicitly authorized final publication after all acceptance and verification gates pass.
- Make provider status and local resource requirements visible. If the model or host is offline, pause clearly; never invoke a paid fallback.

**Acceptance:** a real local-model run routes a task to a specialist, changes only allowed files in isolation, runs relevant checks, and reports the exact result. Mock tests alone do not satisfy this gate.

### 7. Homepage and downloads

- Keep the homepage a static information/download entry point and clearly explain that the persistent self-hosted backend is separate.
- Present current downloads, platform prerequisites, and project status accurately. Separate available, in-development, planned, and externally gated functionality.
- Show the complete target matrix (Windows, Linux, ChromeOS, Android, iOS) and explicitly label which downloadable builds exist and which devices still need real-hardware verification.
- Use StreamioV's local vector identity and the zero-revenue/zero-spend promise without claiming zero electricity, internet, hardware, legal, or platform costs. State clearly that StreamioV itself has no ads, sales, paid gifts, or payment collection.
- Keep legal, privacy, accessibility, and support links accurate; never claim a live server or approved TikTok feature without a current check.

**Acceptance:** every call to action resolves to a real page or artifact; homepage passes keyboard/mobile review; public claims match release and verification evidence.

### 8. Release and verification

- Run focused tests for each change, then integration/security checks required by the relevant workstream.
- Verify download hashes, installer behavior, permissions, logs, and error states on real supported devices where available.
- The owner explicitly requests autonomous publication of the completed work at the end. After acceptance criteria, tests, cost checks, and security review pass, publish the code, homepage, and releases without another confirmation request.
- Do not provision paid resources, publish credentials, weaken security, claim unverified support, or activate TikTok scopes that have not been approved. If an external gate remains, publish only the truthful completed portions and clearly report what is still gated.

## Current local progress

- Added `docs/ZERO_COST_ARCHITECTURE.md` with the zero-additional-cash and no-required-hosted-vendor rules.
- Added `docs/IMPLEMENTATION_SEQUENCE.md` to map all requested product areas and the publication gates.
- Added first-draft vector mark, wordmark, and dependency-free, skippable game intro/outro preview under `games/branding/`; JavaScript syntax check passed.
- Redesigned both homepage copies, added the StreamioV vector assets, target platform matrix, no-revenue promise, and honest Studio/KI/music/TikTok status. Static link/anchor checks passed; no deployment was made.
- Corrected Electron's actual startup `loadFile` target to `regie-v2.html` (the page already used by the trusted-sender checks) and added a regression assertion. The focused Studio suite passes 16 tests. No owner-controlled, continuously reachable application host is evidenced in this checkout; GitHub Pages remains static and no server is being claimed as provisioned.
- Added `host/server.py`, a standard-library-only self-host bootstrap serving the static homepage and non-sensitive health/status routes, with path traversal/symlink protection, a localhost-only default, and an enforced TLS certificate/key requirement for non-loopback binds. Its AI status route checks only local model readiness; it does not execute tasks or permit cloud fallback. Added SQLite-backed local accounts, salted password hashes, random revocable sessions, closed-by-default registration, and a responsive `/account/` page. OAuth and AI task APIs remain unimplemented; host install and uptime on owner hardware are unverified. Focused auth and live HTTP tests pass (`host/README.md`).
- Owner believes their existing host runs Linux. The systemd template is the current target, but the OS and systemd availability must be verified on that actual machine before any installation; the development container's nginx listener is not evidence of the owner's host.
- Added nine local specialist roles (`software`, `studio`, `games`, `music_rights`, `moderation`, `gifts`, `design`, `integration`, `quality`) with role-specific prompts and enforced write allowlists. Added the role CLI option and regression tests. `python3 -m unittest tests.test_phase1_agent tests.test_agent_response_parsing -v` passed 34 tests; Python compilation and `git diff --check` passed.
- Reconstructed the existing Star Defender ZIP prototype into auditable source under `games/releases/streamiov-star-defender/`: the deterministic game engine is separate from the Tkinter renderer, has bounded movement, scoring/difficulty, pause, restart, title and credits screens, and a provenance manifest. Added a versioned ZIP with SHA-256 sidecar. All five engine tests pass, and a real Tkinter window smoke passed for title rendering, Enter input, and playfield rendering on the development host. Python compilation, manifest JSON parsing, and `git diff --check` pass. It remains a prototype: no target-device or full gameplay review, no accessibility review, no ownership transfer evidence, and no second genre release.
- Added `games/catalog.py` as a reusable game-package audit for strict manifest parsing, safe repository paths, package checksum/ZIP integrity, exact source/archive file parity, embedded-manifest consistency, provenance fields, and release gates for gameplay, accessibility, rights, release review, and device testing. The Game AI role now requires this audit and blocks prototypes from release. It validates evidence claims; it does not replace actual reviews or verify ownership by itself.
- Added `games/package.py` for reproducible standard-library ZIP builds from each manifest's exact file list, with a fixed archive timestamp, checksum sidecar, traversal/symlink rejection, and explicit `--force` for replacing a different local artifact. Its three tests pass for reproducibility, stale artifact protection, traversal, and symlink rejection.
- Music library schema advanced to v2: each track declares its protected components and each exact territory/use grant identifies covered components, source title/publisher/section/type, rightsholder, grant basis, attribution, reviewer, and zero-cost evidence. Candidate/partial component grants remain blocked. Explicit sexual content is blocked by default until an age policy exists; political direction remains non-gating. Focused library and local rights-dossier tests cover component-level evidence and unknown rights. Automatic online song discovery remains unimplemented; the dossier only organizes locally recorded evidence.
- The game catalog suite now passes five cases, including blocked release without complete reviews, rejecting a stale package, rejecting an archive with mismatched checksum/corrupt ZIP, and refusing manifests outside the repository. The downloadable archive was extracted to a temporary directory and all five bundled engine tests passed there as well. `gui_smoke.py` passed against the available Tk display after the title-screen mark was aligned to the shared StreamioV symbol.
- GitHub issue #3 and the upstream roadmap identify Neon Relay (reflex arcade), Echo Grid (sequence-memory puzzle), and Pulse Defender (wave shooter), all still `development` and not gameplay-verified; they also record earlier Chromium smoke checks and a real-device gameplay requirement. Imported each as a local independent project, embedded the StreamioV intro, and built deterministic prototype packages with checksums. All three package/catalog audits pass and all local inline JavaScript parses with Node. This environment has no browser executable or Playwright/Puppeteer, so interaction, actual HD viewport, touch-device, and gameplay verification remain open. Signal Weave is an additional spatial-routing puzzle with responsive, resolution-independent SVG/CSS intended for HD/Full HD; its static tests pass, while real-device checks remain open.
- A permitted read-only `python3 -m ai --doctor` check found no model server at `127.0.0.1:11434`; no Ollama or llama.cpp executable is installed on this current host, which has about 213 MiB available RAM. Specialist routing is tested, but live local-model inference is not verified; evidence and setup limits are in `docs/ai-development/SPECIALIST_ROLES.md`.
- Existing user changes in Studio, download page, tests, and untracked files are preserved.
- TikTok account binding and gallery behavior are specified against official Login Kit and approved scopes. Official gift sending/event access and exact TikTok payout values remain external/unverified; StreamioV will not process or deduct money.
- Owner has requested that finished, verified deliverables be published autonomously at the end, subject to zero-cost, security, and truthful-status gates.

## Completion pass 2026-11-03

This pass closed the internally implementable gaps and kept every external gate labelled as gated.

### Fixed correctness issues

- Host static root now serves the complete site copy at `dist/streamiov-homepage-worker/public`, and directory URLs such as `/download/` resolve to their `index.html`. A crawl test checks every local homepage link.
- Studio AI bridge now uses the documented host contract: `127.0.0.1:8765`, `/api/v1/auth/login`, `/api/v1/auth/logout`, `/api/v1/ai/tasks`, cookie sessions, and `X-Streamiov-Client: studio`.
- The host exposes `POST /api/v1/ai/tasks` as an authenticated, rate-limited placeholder that returns `503 ai_execution_not_ready`. It never reports a fake success and never stores the task.
- Packaged Studio builds no longer crash when optional Python modules are absent. Module, status, music-test, and camera-lab handlers return `not_bundled` with an explanation.
- Installer packaging excludes `release/`, `squashfs-root/`, stale HTML copies, backups, bytecode, and cache directories.
- The download package is now a clearly labelled 2026-11-03 source snapshot, not an installer. Each of its seven parts has a fixed size and SHA-256 checksum; the browser combiner verifies each part before writing and documents the assembled archive hash in `SHA256SUMS.txt`.
- The unlinked stale 16 KB Android APK was removed from the public download directory. The download page already states that no tested mobile app exists.

### Studio features

- Persistent scene model v2 stores a background colour and an ordered source list per scene. Source types are camera, screen, title card, and text, each with position, size, layer, visibility, and optional text.
- Actions cover adding, updating, removing, reordering, and hiding sources, changing the background, and deleting or renaming custom scenes. Version 1 scene files migrate automatically.
- One canvas renderer draws the preview monitor, the program monitor, and the encoded stream output. Gifts and alerts are drawn into the same program canvas, so they appear in the stream output rather than only in the UI.
- The source dialog, source list, background picker, and scene controls are wired to the persistent model.
- Tool panels are wired: local chat, local TTS via `espeak-ng`, free local gift effects, local alerts, local audio-file playback, prototype game list, local-host AI login/submit, and read-only device/module diagnostics. Panels state clearly when a capability is local-only, unavailable, or externally gated.

### Raw-data catalog

- `host/data_store.py` seeds a separate SQLite database (`<data-dir>/streamiov-data.sqlite3`) from `data/game_actions/*.json`, `data/music/*.json`, `data/overlays/pro_builder.json`, `data/stickers/*.json`, and the game-preparation specs. It never opens `data/db/streaminivo.sqlite3` or `data/db/streamiov.sqlite3`.
- The host exposes read-only `GET /api/v1/catalog`, `/api/v1/catalog/gifts`, `/api/v1/catalog/games`, `/api/v1/music/library`, and `/api/v1/studio/templates`. `/api/v1/status` reports catalog counts and import errors. `--raw-data-root` / `STREAMIOV_RAW_DATA_ROOT` selects the JSON tree.
- Seeding is idempotent: rows written from JSON are marked `source='seed'` and replaced on the next successful import; other rows are preserved. Missing or invalid JSON is reported without crashing the host or deleting the last valid catalog.
- The seeded catalog currently contains 18 StreamioV gift previews (no TikTok gift IDs), 2 locally registered test games with 3 actions, 1 test playlist with 1 `test-only` track, an empty rights catalog, and 5 local template specifications.
- Studio's gift, game, and music panels load this catalog through the sender-guarded `studio:data-query` IPC bridge, which uses a fixed endpoint allowlist. The 18 gift SVGs are published under `/assets/gifts/`; missing images fall back to a local symbol.

### Homepage, download hub, and deployment checks

- The homepage now has a central downloads section linking the installer, source snapshot, PWA, five game prototypes, account/forum, and the honest verification table. AI, game, and music cards distinguish implemented/tested work from externally blocked inference, unreleased prototypes, and read-only test catalog data.
- The download hub centralizes all local artifacts: three Studio installer families, the seven-part source snapshot, the Web-Regie/PWA, five checksummed game-prototype ZIPs, account/forum links, and a built/verified/prototype/blocked table.
- `public/_headers` declares baseline security headers and a one-hour cache for `/downloads/` assets. It is consumed by Cloudflare Workers static assets; the local Python host does not interpret it.
- `scripts/verify-cloudflare-config.py` validates the assets-only homepage Worker, the AI Worker binding and pinned model, bearer authentication, deploy-script contents, public entry points, security headers, and all download checksums without contacting Cloudflare.
- `.github/workflows/cloudflare-checks.yml` runs those checks and the Worker contract tests on pull requests and `main` pushes. `.github/workflows/cloudflare-deploy.yml` is manual, requires the `production` environment and owner-provided secrets, and makes no deployment claim by itself.
- `release-game.yml` now targets `main` instead of the deleted `streamiov-build-setup-clean` branch.

### Verification

- `python3 -m unittest discover -s tests -p 'test_*.py'`: 253 tests pass.
- `node --test tests/test_cloudflare_ai_worker.mjs`: 12 tests pass.
- `node --test tests/tiktok-oauth.test.js`: 8 tests pass.
- `node --test games/tests/library.test.cjs`: 6 tests pass.
- Prototype game tests: Echo Grid 1, Neon Relay 1, Pulse Defender 1, Signal Weave 5, Star Defender engine 5.
- `node --test engine/*.test.js` in the Studio: 27 tests pass.
- `python3 scripts/verify-cloudflare-config.py`: all offline config, link, header, and checksum checks pass.
- `node --check` passes for `main.js`, `preload.js`, `media-pipeline.js`, `combine.js`, and every inline Regie script.
- The published download parts are assembled and hashed in a Node check that mirrors `combine.js`, and `sha256sum -c SHA256SUMS.txt` passes for all seven parts.
- Publicly served backup files and unlinked stale archives were removed from the site root; a host test fails if backup, secret, or unexpected download files reappear.
- The Studio declares no runtime npm dependencies; the unofficial `tiktok-live-connector` package was removed from `package.json` and the lockfile.
- `python3 -m ai --doctor` exits 3 in this environment because no local model is reachable. That is an honest external limit, not a passing inference test.

### Still externally gated

- TikTok app review, approved scopes, and any official gift-event/sending capability.
- A real live broadcast received and published by a streaming service.
- Real-hardware checks on Windows, ChromeOS, Android, and iOS.
- Local model inference on a machine with enough memory for the selected model.
- Code signing, public hosting, and legal rights review.
