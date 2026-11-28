# StreamioV Host bootstrap

This is the first self-hosted host component. It uses only Python's standard library, serves the complete static site from `dist/streamiov-homepage-worker/public`, and exposes non-sensitive diagnostic routes:

- `GET /healthz` reports process health, version, uptime, and per-store SQLite integrity; it returns `503 degraded` when a database is missing, corrupt, or has drifted from the required schema.
- `GET /api/v1/status` reports that local account routes are enabled while the broader application API remains unavailable, plus read-only catalog counts and import errors.
- `GET /api/v1/catalog`, `/api/v1/catalog/gifts`, `/api/v1/catalog/games`, `/api/v1/music/library`, and `/api/v1/studio/templates` expose the read-only catalog seeded from the repository JSON files under `data/`. They never read or modify the legacy `data/db/*.sqlite3` databases and never import accounts, sessions, devices, or platform credentials.
- `GET /api/v1/music/gate?territory=DE&usage=live_stream`, `GET /api/v1/music/dossier?track=<id>&territory=DE&usage=live_stream`, and `GET /api/v1/music/audio/<id>?territory=DE&usage=live_stream` implement a fail-closed local rights gate. A track is playable only when every required rights component has exact, zero-cost evidence for that territory and use, the content review is approved, and its audio file resolves inside `--music-root`. The audio route is loopback-only, returns no filesystem paths, and sets `Access-Control-Allow-Origin: null` for the local Studio `file://` origin. It never downloads, buys, uploads, or streams external music.
- `GET /api/v1/ai/status` checks only whether a configured loopback Ollama or local OpenAI-compatible model endpoint is ready. It never submits a task and rejects cloud-provider mode.
- `POST /api/v1/auth/register` and `/api/v1/auth/login` create a local username/password account and an HttpOnly session cookie. `GET /api/v1/auth/me` reads the current account and `POST /api/v1/auth/logout` revokes its session.
- `POST /api/v1/ai/tasks` requires a valid session cookie and `X-Streamiov-Client: studio`, validates the request, records a durable task, and submits it only to a configured loopback/local model. It returns a read-only JSON `answer` with provider, model, and `task_id` metadata; without a ready local model it fails closed with `503 ai_execution_not_ready` and stores the failed task. `GET /api/v1/ai/tasks` and `GET /api/v1/ai/tasks/<id>` list and read only the signed-in owner's durable task records. Tasks have no tools and never fall back to a cloud provider.
- `GET/POST /api/v1/wishbox/orders`, `GET /api/v1/wishbox/orders/<order_id>`, `GET /api/v1/wishbox/handoffs`, and `POST /api/v1/wishbox/orders/<order_id>/<dispatch|claim|reject|clarify|complete>` implement the owner-scoped Wunschbox order centre. A request requires a session cookie, `X-Streamiov-Client: studio`, an exact same-origin `Origin` (or trusted loopback Studio main process), and passes a 30-per-10-minute limit. Orders have a unique id, sender, music/game classification, priority, status, assignee, result, feedback, and full status history. Music requests are accepted only when the exact title is in the local rights catalogue and approved for `live_stream`; otherwise they fail closed with viewer feedback. Game requests are handed to the `gaming` agent with advisory-only constraints, never game input, cheats, or automation; the streamer can reject or dispatch every order. Status transitions publish redacted `wishbox.order.*` events to the event ledger.
- `GET/POST /api/v1/events` is a durable, schema-v1 event ledger for the local Studio. Writes require a session cookie, `X-Streamiov-Client: studio`, and an exact same-origin `Origin` from the browser; a loopback Studio main process may use the client header instead. Events are idempotent by `event_id`, owner-scoped on reads, capped at 60 writes per ten minutes, validated to flat scalar data, and redacted for credential-like keys and RTMP URLs. It records Studio actions only; it is not a gift transaction, payout, or platform event ledger.
- `GET /api/forum/threads` and `GET /api/forum/threads/<id>` are public reads of the community forum. `POST /api/forum/threads` and `POST /api/forum/threads/<id>/replies` require a host session, an exact same-origin `Origin`, a JSON body, and pass per-IP rate limits (5 new threads and 20 replies per 600 seconds). Titles are 3–140 characters, thread bodies up to 10,000, replies up to 5,000. Locked threads reject replies with `423`; deleted entries are soft-deleted.
- Other `GET`/`HEAD` requests serve files contained in the configured static site directory, including directory indexes such as `/download/`. The download hub also serves five checksummed game-prototype ZIPs and their `SHA256SUMS-games.txt`; these are development prototypes, not released games. Cloudflare Workers static assets use the checked-in `public/_headers` file for baseline security headers; the local Python host does not interpret that file.

Accounts are stored in a local SQLite database under `--data-dir` (default `~/.local/share/streamiov-host`). The catalog is stored separately in the same directory as `streamiov-data.sqlite3`; the forum is stored in `forum.sqlite3`; failed and completed AI task records are stored in `ai_tasks.sqlite3`; Studio event records are stored in `events.sqlite3`; Wunschbox orders and their history are stored in `wishbox.sqlite3`. Seeding replaces only rows marked `source='seed'` and keeps manually added rows. A missing or invalid JSON source is reported in `/api/v1/status` without crashing the host or discarding the last valid catalog. Use `--raw-data-root` (or `STREAMIOV_RAW_DATA_ROOT`) to point at a different JSON tree. Approved audio files are read only from `--music-root` (or `STREAMIOV_MUSIC_ROOT`), defaulting to `DATA_DIR/music`; symlinks leaving that directory and files over 32 MiB are denied. Web registration is **closed by default**;
 create the owner's first account from a local terminal with `--create-account USERNAME`. Public self-registration requires the explicit `--enable-registration` flag and is not approved for the current bootstrap. Passwords use salted PBKDF2-HMAC-SHA256 hashes; opaque session tokens are random and only their SHA-256 hashes are stored. Browser authentication mutations require an exact same-origin `Origin`; the local Electron main process may instead identify itself with `X-Streamiov-Client: studio` from a loopback address. Both paths use an in-memory per-IP rate limit and return `HttpOnly; SameSite=Strict` cookies; cookies gain `Secure` when this process terminates TLS. The PBKDF2 work factor is 600,000 HMAC-SHA256 iterations, matching OWASP's recommendation for its FIPS-constrained PBKDF2 case; this implementation does not claim FIPS compliance. Python's standard library supplies the PBKDF2 primitive.

The static site includes `/account/`, a small client for these local account routes. It reports when served without the StreamioV account host, keeps TikTok connection disabled until official app setup and approval exist, and never requests TikTok credentials. The first account must be created through the local operator command because registration is closed by default.

This is still not ready for public accounts: there is no password recovery, email verification, account deletion UI, approved live OAuth provider connection, durable AI task executor with tools, catalog write API, or platform gift/music integration. The host has local OAuth callback, token exchange, refresh, and disconnect routes, but they are not a live platform integration and need approved provider credentials plus real verification before any platform is reported connected. The guarded AI task endpoint now records durable task history, but it still performs read-only local inference only, exposes no tools, and fails closed when no local model is ready. The event ledger records validated, redacted Studio actions for the signed-in owner; it is not a transaction ledger and has no external event source. The forum has authenticated writes, operator moderation, abuse reports, per-user history, and advisory spam signals, but no email notifications; its documented local retention policy is applied only by the operator CLI and never automatically. The read-only catalog endpoints describe local seed data only and do not buy, send, or receive gifts. The music gate verifies only locally recorded rights evidence for the exact requested territory and use; it is not a substitute for a legal review or a licensed streaming service. Before any remote user rollout,
 review registration abuse controls, password reset/admin recovery, privacy/data-retention terms, TLS certificate operations, and reverse-proxy behavior. GitHub Pages remains a static alternative for the project site; this process does not make GitHub run a persistent server.

## Run locally

From the repository root:

```sh
python3 host/server.py
```

Open `http://127.0.0.1:8765/` and check `http://127.0.0.1:8765/healthz`. The read-only catalog is available at `http://127.0.0.1:8765/api/v1/catalog`; the local rights gate is reported under `/api/v1/status` as `music_gate`. The default bind is loopback only.
 Local HTTP is permitted only on loopback. Any non-loopback bind is rejected unless both `--tls-cert` and `--tls-key` are provided; TLS alone does not make the unfinished application routes ready for public users.

Create or reset the local owner's account with `python3 host/server.py --create-account USERNAME` or `python3 host/server.py --reset-password USERNAME`. Both commands prompt securely in the terminal and exit without starting the HTTP server. For normal use, the account UI is at `/account/`. Password recovery by email is not implemented.

## Local Core backup and restore

The operator can create, list, verify, restore, and run the local schedule without starting the HTTP server:

```sh
python3 host/server.py --data-dir DIR --backup-create
python3 host/server.py --data-dir DIR --backup-list
python3 host/server.py --data-dir DIR --backup-prune --backup-keep 3
python3 host/server.py --data-dir DIR --backup-verify BACKUP_DIR
python3 host/server.py --data-dir DIR --backup-restore BACKUP_DIR
python3 host/server.py --data-dir DIR --backup-restore BACKUP_DIR --backup-force
python3 host/server.py --data-dir DIR --backup-schedule-status
python3 host/server.py --data-dir DIR --backup-schedule-run
```

Backups default to `DIR/backups`; `--backup-dir` changes the output/list root. Pruning deletes only valid backups beyond the newest `--backup-keep` count (at least 1) and leaves invalid directories for inspection. Each backup contains a versioned manifest, consistent SQLite snapshots of the known Core databases (`accounts.sqlite3`, `forum.sqlite3`, `streamiov-data.sqlite3`, `ai_tasks.sqlite3`, `events.sqlite3`, `wishbox.sqlite3`, `music.sqlite3`, `platform_connections.sqlite3`), and the token encryption key when present. A database that is absent at backup time is recorded as absent in the manifest, reported as absent by verify/restore output, and never fabricated. All files are `0600`, the manifest records sizes and SHA-256 hashes, and verification checks hashes plus SQLite integrity before any restore. Restore refuses to replace existing Core files unless `--backup-force` is given; it preserves unrelated files and removes stale WAL/SHM/journal sidecars for replaced databases. Stop the host before restoring.

The local schedule is defined in `infrastructure/backup/core/backup-policy.json` and can be overridden with `--backup-policy FILE`. When `schedule.enabled` is true, a running host starts a daemon that creates one backup per `interval_minutes`, verifies it, prunes to `keep`, and records a bounded private status in `DIR/backups/backup-schedule.json`; a failed cycle records its error and retries at the next interval. `--backup-schedule-status` shows policy and last results without starting the server, while `--backup-schedule-run` forces one cycle immediately. Backup roots must be simple local directory names, and the schedule never restores automatically. Backups remain local only: there is no cloud upload, no bundled music-audio copy, and no verified production restore; a backup containing the token key must be stored with the same care as the key itself.

## Forum moderation

The community forum is available at `/forum/`. Reads are public. Writing requires a host session and uses the same account cookie as `/account/`. The forum UI loads `/api/v1/auth/me`, links to `/account/` for sign-in, and reports authentication, same-origin, rate-limit, locked-thread, and validation errors without pretending a write succeeded.

Set `STREAMIOV_FORUM_MODERATORS` to a comma-separated list of local account user IDs before starting the host to enable in-page moderation. Unset means nobody is a moderator: the HTTP report queue and resolve/dismiss actions fail closed, while the CLI below still works for the operator who owns `--data-dir`. A moderator's `/api/v1/auth/me` response includes `is_forum_moderator: true`; `/forum/` then shows `/api/forum/reports` with resolved/dismissed buttons that POST to `/api/forum/reports/<id>/resolve`.

Moderate from the host machine without starting the server:

```sh
python3 host/server.py --forum-list
python3 host/server.py --forum-lock THREAD_ID
python3 host/server.py --forum-unlock THREAD_ID
python3 host/server.py --forum-delete-thread THREAD_ID
python3 host/server.py --forum-delete-reply REPLY_ID
python3 host/server.py --forum-reports
python3 host/server.py --forum-resolve-report REPORT_ID resolved
python3 host/server.py --forum-resolve-report REPORT_ID dismissed
python3 host/server.py --forum-spam
python3 host/server.py --forum-history USER_ID
python3 host/server.py --forum-retention-status
python3 host/server.py --forum-retention-run
python3 host/server.py --forum-retention-schedule-status
python3 host/server.py --forum-retention-schedule-run
```

`--forum-list` prints recent threads and replies as JSON lines, including soft-deleted entries. `--forum-reports` prints all abuse reports with their current status; `--forum-resolve-report` resolves or dismisses one open report and records the local CLI operator as resolver. `--forum-spam` prints visible posts carrying advisory spam flags, and `--forum-history` prints one user's visible threads and replies. Deletes are soft deletes, so the row remains available for operator review. `--forum-retention-status` prints the policy and the number of eligible records without changing data; `--forum-retention-run` applies it in one transaction. The policy keeps visible posts and open reports, expires resolved reports and soft-deleted content after 90 days, moderation actions after 180 days, read notifications 30 days after reading, and unread notifications 90 days after creation. `--forum-retention-schedule-status` reports the optional schedule and its last result; `--forum-retention-schedule-run` forces one scheduled cycle immediately. Both accept `--forum-retention-policy FILE`. The checked-in policy at `infrastructure/forum/retention-policy.json` has `schedule.enabled: false`: a running host starts no retention daemon, and automatic deletion stays off until an owner explicitly enables it in a local policy file after the required legal review. When enabled, a daemon runs at most once per `interval_minutes` (60–10080), uses the same transactional deletion, and records bounded private status in `DIR/forum-retention/forum-retention-schedule.json`. A failed cycle records its error and retries at the next interval; the daemon never restores data and never runs while the policy or state file is invalid. The in-page moderator queue is available only to IDs listed in `STREAMIOV_FORUM_MODERATORS`; run these commands as the same operating-system user that owns `--data-dir` so database permissions stay correct.

## OAuth connection persistence

`services/oauth/connection_service.py` provides fail-closed local persistence for platform connections that have already been verified. Tokens are encrypted with `services/oauth/token_crypto.py`; only a reference, scopes, expiry, and account identity are returned by `get_connection_status`. Plaintext tokens are never written to SQLite and are only available to server-side code through `get_tokens`.

Set `STREAMIOV_TOKEN_KEY` to a private high-entropy value, or place that value in a `0600` key file at `oauth-token.key` inside `--data-dir`. Without either, storing a token raises an error instead of falling back to a built-in key. The store accepts only `twitch` and `tiktok`, hashes OAuth state before storage, expires state after ten minutes, requires the matching state when saving a connection, and clears all token fields on disconnect.

This is a storage layer only. It does not implement a provider login page, callback, token exchange, or live publication, and no platform is described as connected until a verified connection has actually been saved.

## Shared rate limiting

Set `STREAMIOV_SHARED_RATE_LIMIT_DB` to one explicit SQLite file path to coordinate the host's throttles across multiple host processes and multiple host data directories. `host/shared_rate_limiter.py` stores HMAC-SHA-256 buckets (never plaintext client addresses) in that file, serializes each sliding-window check with `BEGIN IMMEDIATE`, caps buckets, prunes expired attempts, and denies the request on any storage error. An invalid or unreadable path stops startup instead of silently weakening the limit. `/api/v1/status` then reports `shared_rate_limiter` without credentials. Without the variable, existing in-memory and per-data-directory persistent limiters remain unchanged.

This is a shared-file limiter, not a network service: machines that do not share a filesystem have separate budgets, and wall-clock skew between them affects the sliding window. A truly global multi-datacentre limiter would require a separately owned, available service and is not claimed here. No such service, deployment, or production evidence exists in this repository.

## Linux start-at-boot template

`systemd/streamiov-host.service` is a template for an installation at `/opt/streamiov`. It runs as a restricted `streamiov` system user, stores account data under `/var/lib/streamiov-host`, restarts after process failure, limits memory/tasks, and binds only to localhost. It is not enabled on this development machine. Create the service user and owner account locally before enabling it; run account create/reset commands as `streamiov` so database ownership stays correct. The optional `nginx/streamiov-host.conf.example` shows TLS termination on an already configured Nginx host and overwrites forwarded headers; it is a template, not an installed or verified site configuration. Verify a local install with `systemctl status streamiov-host` and `curl http://127.0.0.1:8765/healthz`. A running local service still does not make the site public or provide a trusted certificate by itself.

## Cost and uptime

The software has no license or service fee and downloads no dependencies. It stays available only while an already-owned host computer is powered, connected, and running this process. Power, internet, router, public IP/CGNAT, and existing hardware availability are outside the software's control. This repository does not prove that a StreamioV host is currently deployed or continuously reachable.

## Current stage

This is a static site and local account/health bootstrap, not the final StreamioV application server. The AI task route is a fail-closed local inference endpoint with durable owner-scoped history, not a tool-using executor. The raw-data catalog is read-only and seeded from repository JSON; it is not a platform gifts/music integration. The community forum is a real authenticated local write surface with operator moderation and a documented local retention policy, but it is not a public-community rollout. The next gates are secure host installation on owner-controlled hardware, remote deployment review, public account signup/recovery policies, automatic retention scheduling with legal review, a tool-using local AI executor, and measured uptime on the selected machine. No OAuth credentials or tokens are read or modified by this bootstrap.
