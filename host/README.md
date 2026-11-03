# StreamioV Host bootstrap

This is the first self-hosted host component. It uses only Python's standard library, serves the complete static site from `dist/streamiov-homepage-worker/public`, and exposes non-sensitive diagnostic routes:

- `GET /healthz` reports process health, version, and uptime.
- `GET /api/v1/status` reports that local account routes are enabled while the broader application API remains unavailable, plus read-only catalog counts and import errors.
- `GET /api/v1/catalog`, `/api/v1/catalog/gifts`, `/api/v1/catalog/games`, `/api/v1/music/library`, and `/api/v1/studio/templates` expose the read-only catalog seeded from the repository JSON files under `data/`. They never read or modify the legacy `data/db/*.sqlite3` databases and never import accounts, sessions, devices, or platform credentials.
- `GET /api/v1/ai/status` checks only whether a configured loopback Ollama or local OpenAI-compatible model endpoint is ready. It never submits a task and rejects cloud-provider mode.
- `POST /api/v1/auth/register` and `/api/v1/auth/login` create a local username/password account and an HttpOnly session cookie. `GET /api/v1/auth/me` reads the current account and `POST /api/v1/auth/logout` revokes its session.
- `POST /api/v1/ai/tasks` is an authenticated placeholder for the Studio AI bridge. It requires a valid session cookie and `X-Streamiov-Client: studio`, validates the request, and returns `503 ai_execution_not_ready`. It does not store or execute the task.
- Other `GET`/`HEAD` requests serve files contained in the configured static site directory, including directory indexes such as `/download/`.

Accounts are stored in a local SQLite database under `--data-dir` (default `~/.local/share/streamiov-host`). The catalog is stored separately in the same directory as `streamiov-data.sqlite3`; seeding replaces only rows marked `source='seed'` and keeps manually added rows. A missing or invalid JSON source is reported in `/api/v1/status` without crashing the host or discarding the last valid catalog. Use `--raw-data-root` (or `STREAMIOV_RAW_DATA_ROOT`) to point at a different JSON tree. Web registration is **closed by default**; create the owner's first account from a local terminal with `--create-account USERNAME`. Public self-registration requires the explicit `--enable-registration` flag and is not approved for the current bootstrap. Passwords use salted PBKDF2-HMAC-SHA256 hashes; opaque session tokens are random and only their SHA-256 hashes are stored. Browser authentication mutations require an exact same-origin `Origin`; the local Electron main process may instead identify itself with `X-Streamiov-Client: studio` from a loopback address. Both paths use an in-memory per-IP rate limit and return `HttpOnly; SameSite=Strict` cookies; cookies gain `Secure` when this process terminates TLS. The PBKDF2 work factor is 600,000 HMAC-SHA256 iterations, matching OWASP's recommendation for its FIPS-constrained PBKDF2 case; this implementation does not claim FIPS compliance. Python's standard library supplies the PBKDF2 primitive.

The static site includes `/account/`, a small client for these local account routes. It reports when served without the StreamioV account host, keeps TikTok connection disabled until official app setup and approval exist, and never requests TikTok credentials. The first account must be created through the local operator command because registration is closed by default.

This is still not ready for public accounts: there is no password recovery, email verification, account deletion UI, OAuth callback, working AI task executor, catalog write API, or platform gift/music integration. The read-only catalog endpoints describe local seed data only; they do not buy, send, or receive gifts and do not verify music rights. Before any remote user rollout, review registration abuse controls, password reset/admin recovery, privacy/data-retention terms, TLS certificate operations, and reverse-proxy behavior. GitHub Pages remains a static alternative for the project site; this process does not make GitHub run a persistent server.

## Run locally

From the repository root:

```sh
python3 host/server.py
```

Open `http://127.0.0.1:8765/` and check `http://127.0.0.1:8765/healthz`. The read-only catalog is available at `http://127.0.0.1:8765/api/v1/catalog`. The default bind is loopback only. Local HTTP is permitted only on loopback. Any non-loopback bind is rejected unless both `--tls-cert` and `--tls-key` are provided; TLS alone does not make the unfinished application routes ready for public users.

Create or reset the local owner's account with `python3 host/server.py --create-account USERNAME` or `python3 host/server.py --reset-password USERNAME`. Both commands prompt securely in the terminal and exit without starting the HTTP server. For normal use, the account UI is at `/account/`. Password recovery by email is not implemented.

## Linux start-at-boot template

`systemd/streamiov-host.service` is a template for an installation at `/opt/streamiov`. It runs as a restricted `streamiov` system user, stores account data under `/var/lib/streamiov-host`, restarts after process failure, limits memory/tasks, and binds only to localhost. It is not enabled on this development machine. Create the service user and owner account locally before enabling it; run account create/reset commands as `streamiov` so database ownership stays correct. The optional `nginx/streamiov-host.conf.example` shows TLS termination on an already configured Nginx host and overwrites forwarded headers; it is a template, not an installed or verified site configuration. Verify a local install with `systemctl status streamiov-host` and `curl http://127.0.0.1:8765/healthz`. A running local service still does not make the site public or provide a trusted certificate by itself.

## Cost and uptime

The software has no license or service fee and downloads no dependencies. It stays available only while an already-owned host computer is powered, connected, and running this process. Power, internet, router, public IP/CGNAT, and existing hardware availability are outside the software's control. This repository does not prove that a StreamioV host is currently deployed or continuously reachable.

## Current stage

This is a static site and local account/health bootstrap, not the final StreamioV application server. The AI task route is a fail-closed placeholder, not an executor. The raw-data catalog is read-only and seeded from repository JSON; it is not a platform gifts/music integration. The next gates are secure host installation on owner-controlled hardware, remote deployment review, public account signup/recovery policies, write APIs for user-created data, a real local AI task executor, and measured uptime on the selected machine. No OAuth credentials or tokens are read or modified by this bootstrap.
