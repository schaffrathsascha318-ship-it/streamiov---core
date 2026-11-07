# Durable queue controls

The SQLite-backed `SpecialistTaskQueue` exposes operator controls for a
self-hosted Core service:

- `pause(actor=...)` prevents new task claims. Already-running workers are
  allowed to finish; lease recovery still runs while paused.
- `resume(actor=...)` permits claims again.
- `cancel_task(task_id, actor=...)` cancels a task only while it is queued.
  Running work is not force-killed because the current worker contract has no
  cooperative cancellation token. The API must return this limitation rather
  than report a running task as cancelled.
- `is_paused()` reads the persisted global pause state.
- `audit_log(limit=...)` returns newest-first operator and task lifecycle
  events. The limit is bounded to 1–1000.

Pause state, task state changes, and their audit entries are stored in SQLite.
Audit rows have database triggers that reject ordinary UPDATE and DELETE
statements. This is append-only protection within the application database,
not tamper-proof/WORM storage against a database administrator who can alter
the schema or replace the database file.

The queue API accepts an `actor` label for audit attribution. Any future
network control API MUST derive this value from the authenticated server-side
principal; it must never trust an actor name supplied by the caller.

Existing queue databases are migrated transactionally to support the explicit
`cancelled` status. Existing task rows and their queue order are preserved.
A cancelled prerequisite causes queued dependants to be skipped.

These controls are library-level primitives only. They do not expose a network
endpoint, CLI command, web UI, or production service. No service is deployed.
