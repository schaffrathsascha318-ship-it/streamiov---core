# STREAMIOV OpenCode Core

## Purpose

OpenCode Core is the server-side execution service for the persistent STREAMIOV specialist queue. Development devices are clients and control surfaces; they are not the hosting server. The service supervises a bounded worker pool and can resume queued work after a process restart because task state is stored in SQLite.

This is an implementation foundation, not a claim of unlimited model capacity or fully autonomous production releases.

## Implemented in this branch

- Persistent SQLite task queue with dependency gating, worker leases and bounded retries.
- Parallel worker pool with 1–8 workers and a shared global task limit.
- Fifteen specialist roles with separate writable path scopes.
- Ordered model failover when the primary provider raises a provider error.
- Graceful SIGINT/SIGTERM handling at the worker-pool supervisor.
- systemd unit template for a dedicated Linux server.

## Model failover configuration

The primary provider uses:

- `STREAMIOV_MODEL_PROVIDER`: `ollama`, `openai-compatible-local`, or `cloudflare-workers-ai`.
- `STREAMIOV_MODEL`, `STREAMIOV_MODEL_URL`.
- For the Cloudflare gateway, `STREAMIOV_AI_WORKER_TOKEN`.

Optional one-step fallback uses:

- `STREAMIOV_FALLBACK_PROVIDER`.
- `STREAMIOV_FALLBACK_MODEL`.
- `STREAMIOV_FALLBACK_MODEL_URL`.
- For a fallback Cloudflare gateway, `STREAMIOV_FALLBACK_AI_WORKER_TOKEN`.

Fallback is attempted only after a provider-level failure such as a network error, HTTP error, or quota response. A separate fallback endpoint and its own valid credentials/access are required. This does not bypass provider quotas, create free capacity, or guarantee that another model is available. Provider credentials belong in the server's environment file or secret manager, never in Git, task prompts, logs, or this document.

## Server installation outline

The unit file at `infrastructure/systemd/streamiov-opencode-core.service` is a deployment template. It assumes:

- A dedicated unprivileged Linux account and group named `streamiov`.
- A checked-out and reviewed repository at `/opt/streamiov`.
- A virtual environment at `/opt/streamiov/.venv`.
- Writable project and state directories for that service account.
- Provider configuration in `/etc/streamiov/opencode-core.env`, readable only by the service account and administrators.

Before enabling the unit, install dependencies, run the project test suite, verify `python -m ai --doctor`, and check filesystem ownership and available disk space. Then install the unit into the systemd unit directory, reload systemd, and start it. This branch does not deploy the service or provision a server.

## Safety and current limitations

- The worker pool executes only tasks already persisted in the queue. It does not yet ingest GitHub issues automatically.
- No automatic push, pull request, merge, production deployment, OAuth change, credential rotation, payment, or release is implemented.
- Specialist write scopes are enforced by ProjectTools, but the service account must also be restricted at the operating-system level.
- Race-safe workspace file operations currently use POSIX `openat`/`O_NOFOLLOW`. The Windows CI job verifies wheel installation, CLI startup, and that workspace reads/writes fail closed; it does **not** provide Windows workspace editing. A handle-relative Windows backend and adversarial Windows filesystem tests are still required before Windows task execution can be enabled.
- Task prompts and model output are untrusted. Review diffs and test results before accepting changes.
- A worker can resume queued tasks after restart; an interrupted running task becomes eligible again only after its lease expires. Idempotency and duplicate side-effect handling still need dedicated tests.
- Current built-in test execution is limited to the existing Python test command. Node/Electron/platform build adapters remain future work.
- Model failover handles provider-level exceptions; it does not retry a syntactically invalid model answer with another model.
- The service is not yet connected to a continuously running planner that creates new work autonomously. New plans must currently be enqueued through the CLI.

## Next milestones

1. Run the Python suite and add concurrency/recovery tests against a temporary SQLite database.
2. Add queue inspection, pause/resume, task cancellation, and structured audit reports.
3. Add an authenticated control API for approved task submission and service health.
4. Add read-only GitHub issue intake with deduplication and prompt-injection defenses.
5. Add test adapters for Node/Electron and platform builds.
6. Add draft-PR publication only after diff review, CI, and explicit approval gates.
7. Deploy to a dedicated server and verify restart recovery before treating the service as continuously available.
