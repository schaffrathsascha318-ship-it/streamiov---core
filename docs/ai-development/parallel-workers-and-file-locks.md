# AI Chief parallel workers and shared-workspace locking

## Execution model

The durable AI Chief mission engine can schedule multiple independently identified tasks in parallel. Each task keeps its own SQLite lease, checkpoint, retry state and final verification. Multiple tasks may use the same specialist role; the role registry is a set of reusable capabilities, not a one-worker-per-role limit.

Configure the worker pool with `STREAMIOV_MAX_CONCURRENT_WORKERS`. The safe default remains **4**. The hard supported range is 1–50, but 50 is a planning/scheduler ceiling, not a production recommendation. Increase only after measuring provider quotas, memory/CPU, host capacity, task overlap and file-conflict rates.

## Write safety

Every repository writer must use `ProjectTools`:

1. Per-path in-process locks serialize writers inside one mission process.
2. POSIX `fcntl.flock` or Windows `msvcrt.locking` coordinates separate processes sharing the same local filesystem.
3. Lock files are outside the checkout, keyed by SHA-256 of the normalized absolute target path, and use restrictive permissions.
4. Lock ownership metadata records the persisted task ID, PID, path hash and acquisition time.
5. The operating system releases the lock when its process exits or crashes. The next successful owner replaces stale metadata.
6. Writes use atomic replacement; create-only operations refuse to overwrite a path another worker created first. Exact-match edits reject stale content.

The lock is advisory. Any process that writes the same checkout without going through `ProjectTools` is outside the guarantee. The lock is local-host coordination, not a distributed lock across independent machines, NFS/remote filesystems or separate CI runners. For high-contention same-file work, use isolated per-task worktrees and merge reviewed patches rather than sharing one checkout.

## Mission completion and recovery

A task is not complete merely because a worker process returned. The durable mission engine still requires task completion evidence, dependency resolution and final verification. Worker shutdown/restart preserves checkpoints and releases OS-level locks on process exit. A restarted supervisor must use the same mission database and the existing exclusive supervisor lease.

## Operational guardrails

- Keep the default concurrency at 4 until representative host load and provider quota measurements justify a change.
- Do not start two independent supervisors against the same mission database.
- Do not share a checkout with external editors, scripts or tools that bypass ProjectTools while workers are active.
- Do not store credentials, OAuth files, environment secrets, deployment workflows or trust-anchor controls in worker-writable paths.
- Do not interpret local file-lock success as proof of multi-host coordination.
- No production deployment, Cloudflare change, OAuth change or credential operation is part of the worker pool.

## Verification

The repository includes planner tests for 50 unique task IDs and repeated specialist roles, concurrent task overlap checks, same-path stale-write tests, atomic reader/writer tests, distinct-path overlap tests and a subprocess crash-recovery test for OS-level locks. CI must pass on the final combined branch before integration.
