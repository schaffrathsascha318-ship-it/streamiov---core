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

Set these only in the service environment after verifying the intended account ID and queue database path:

```sh
STREAMIOV_TASK_QUEUE_DB=/srv/streamiov/data/tasks.sqlite3
STREAMIOV_QUEUE_ADMIN_USER_IDS=the-32-character-user-id
```

Use the same database path with every enqueue/worker invocation, for example:

```sh
opencode-core --queue-db /srv/streamiov/data/tasks.sqlite3 --worker-loop
```

The queue API does not start workers, enqueue new work, expose task prompts/results, or grant workspace access. It is not enabled on any hosted or production system by this code change. Deploying or setting the environment variables requires a separate explicit approval.

## Security boundary

The append-only SQLite audit triggers protect against ordinary application-level UPDATE/DELETE statements, not a database administrator or filesystem owner who can alter the schema or replace the database. Protect the queue database and its parent directory with OS permissions and backups. The HTTP API omits audit details because lifecycle errors and tool output may contain untrusted or sensitive text.
