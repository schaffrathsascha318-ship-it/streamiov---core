# Authenticated task-queue control API

The queue-control HTTP API is disabled unless both configuration values are set:

- `STREAMIOV_TASK_QUEUE_DB`: the exact SQLite database path used by `opencode-core --queue-db` for enqueue/worker operations.
- `STREAMIOV_QUEUE_ADMIN_USER_IDS`: comma-separated internal user IDs explicitly authorized to operate the queue.

The API does not infer administrator rights from a username, accept role or actor fields from requests, or grant permissions to device tokens. Requests must use an active `streamiov_session` cookie. The server derives the audit actor from the authenticated account's immutable user ID. Mutating browser requests require an exact same-origin Origin header; the local Electron main process may use the existing loopback-only `X-Streamiov-Client: studio` exception.

If the database path is not configured, queue endpoints return `503 queue_api_not_configured`. If the session is absent or expired, they return 401. Authenticated users not in the allow-list receive 403. Keep the allow-list empty until an operator is deliberately authorized. Never expose the queue database path or admin IDs to clients.

## Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/v1/queue/status` | Pause state and task counts only; no prompts/results |
| GET | `/api/v1/queue/audit?limit=100` | Recent audit metadata; free-form details are omitted |
| POST | `/api/v1/queue/pause` | Stop new claims; running tasks continue |
| POST | `/api/v1/queue/resume` | Allow claims again |
| POST | `/api/v1/queue/tasks/{task_id}/cancel` | Cancel a queued task only |

Control POST requests accept no body. The API rate-limits mutations. Cancellation of a running task is rejected; it never kills a worker or interrupts a model/tool call. Invalid state transitions return a conflict response.

## Example server configuration

The checked-in systemd units now agree on one explicit database path:

```text
/var/lib/streamiov/queue.sqlite3
```

The worker unit `infrastructure/systemd/streamiov-opencode-core.service` passes that path to `opencode-core --worker-loop`. The host unit `host/systemd/streamiov-host.service` exposes the exact same path to the HTTP API through `STREAMIOV_TASK_QUEUE_DB`. Both units declare the shared `streamiov` state directory and writable path. The host reads the operator allow-list separately from the optional file `/etc/streamiov/queue-admin.env`:

```sh
STREAMIOV_QUEUE_ADMIN_USER_IDS=the-32-character-user-id
```

Keep that file owned by root, readable only by the service account/group as required, and mode-restricted (for example `0640`). Do not put queue credentials or user passwords in it. The queue database remains owned by the `streamiov` service account with a private state directory. Enqueue commands must also use `--queue-db /var/lib/streamiov/queue.sqlite3`; never create a second path for the API and worker.

The worker is supervised by systemd with SIGTERM shutdown and automatic restart. A task interrupted before completion remains in the SQLite database as a leased running task; after its lease expires, the next worker claim recovers it and either retries it within its retry budget or marks it failed. This is at-least-once task execution: a process may have performed an external side effect immediately before dying. Tasks that perform external writes must therefore use idempotency keys or verify prior state before repeating side effects.

These unit-file changes and tests are configuration artifacts only. No unit was installed, enabled, started, restarted, or deployed. Setting the operator allow-list and installing/reloading services require separate explicit approval.

## Security boundary

The append-only SQLite audit triggers protect against ordinary application-level UPDATE/DELETE statements, not a database administrator or filesystem owner who can alter the schema or replace the database. Protect the queue database and its parent directory with OS permissions and backups. The HTTP API omits audit details because lifecycle errors and tool output may contain untrusted or sensitive text.
