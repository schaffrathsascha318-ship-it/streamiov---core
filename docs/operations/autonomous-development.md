# STREAMIOV Autonomous Development Operations

## Purpose

This service runs the existing bounded specialist queue worker as a supervised user service on the Chromebook. It is the first execution layer of the STREAMIOV development operation, not an unrestricted self-modifying agent and not a claim that the entire product can be completed without acceptance tests.

## Existing capabilities used

- SQLite-backed persistent specialist task queue with dependency ordering, worker leases, bounded retries and terminal task states.
- Specialist planner with a validated task DAG (maximum 12 planned tasks).
- Role-specific write prefixes enforced by ProjectTools.
- Agent tool allowlist: list/read files, create new files, exact unique text replacements, and the fixed Python unittest command.
- Supervised worker loop with SIGINT/SIGTERM handling and bounded polling.

The worker processes tasks already present in the queue. It does not currently ingest GitHub issues automatically, create commits or pull requests, run arbitrary shell commands, execute JavaScript/Electron builds, deploy production, or approve its own work. Those are separate capabilities and must not be assumed from a running service.

## Safety boundaries

- Do not put `.env`, OAuth tokens, API tokens, private keys, or creator token files in task prompts, logs, GitHub issues, or model context.
- Keep TikTok OAuth configuration and existing creator connections unchanged. No token migration, secret rotation, revocation, callback/scope change, or forced reauthorization is part of routine agent operation.
- Keep all existing backups and Git history.
- The agent may only write inside the specialist's configured writable prefixes. The operating-system service runs as the Chromebook user; it is not a security boundary against that same user.
- Production deploys, payments/payouts, credential changes, destructive operations, merges and releases require a separate explicit approval.
- Treat model output and project content as untrusted input. Review diffs and test results before accepting a change.

## Prerequisites

1. The repository is checked out at `~/streamiov`.
2. The virtual environment exists at `~/streamiov/.venv` and can run `python -m ai --doctor`.
3. The configured model provider is reachable. The default provider is Ollama at `http://127.0.0.1:11434`; other supported providers are described in `ai/providers/local_http.py`.
4. The user service manager is available (`systemctl --user` works).
5. There is sufficient free disk space for logs, the SQLite queue and builds.

The service deliberately uses a separate optional environment file outside the repository: `~/.config/streamiov/agent.env`. Create it with restrictive permissions and only the variables required by the chosen model provider. Never paste its contents into ChatGPT or commit it. If the configured provider does not need environment variables, the file can remain absent.

## Install and operate

From the Chromebook terminal:

```bash
mkdir -p ~/.config/streamiov
chmod 700 ~/.config/streamiov
mkdir -p ~/streamiov/data/ai-development
chmod 700 ~/streamiov/data/ai-development
mkdir -p ~/.config/systemd/user
cp ~/streamiov/infrastructure/systemd/streamiov-agent.service ~/.config/systemd/user/
systemctl --user daemon-reload
```

Check prerequisites before enabling the service:

```bash
cd ~/streamiov
.venv/bin/python -m ai --doctor
systemctl --user status streamiov-agent.service
```

Start it only after the doctor reports ready:

```bash
systemctl --user enable --now streamiov-agent.service
```

Inspect status and logs:

```bash
systemctl --user status streamiov-agent.service
journalctl --user -u streamiov-agent.service -n 100 --no-pager
```

Stop or disable it:

```bash
systemctl --user disable --now streamiov-agent.service
```

Do not enable lingering automatically. Whether the worker should run when the user is logged out is a separate device/availability decision.

## Queue a task

Use the existing CLI, from the project root:

```bash
.venv/bin/python -m ai --plan-and-enqueue \
  --project-root . \
  --queue-db data/ai-development/queue.sqlite3 \
  --task "Describe one bounded, testable STREAMIOV development goal."
```

The planner persists a validated plan. The supervised worker then claims eligible tasks and records success/failure. A failed prerequisite causes its dependants to be skipped. Review the queue output and the resulting Git diff.

## Current limitations / next engineering milestones

1. Add a read-only GitHub issue intake with label/priority filters and explicit deduplication; never treat every issue comment as executable authorization.
2. Add a durable audit/report format for each task, including changed paths, test command/output, commit SHA and failure reason.
3. Add a controlled patch/branch publisher. The agent must not push directly to `main`; open draft PRs and require CI plus review.
4. Expand test adapters for Node/Electron/PWA and platform-specific builds. The current built-in agent test tool only runs Python unittest discovery.
5. Add health monitoring, disk-space guardrails, queue age alerts, graceful shutdown/recovery and an operator pause switch.
6. Add a supervised issue-to-task loop only after intake, prompt-injection handling, scope enforcement and audit tests pass.
7. Keep release, deployment, OAuth/secret, financial and destructive actions outside autonomous approval.

## Acceptance criteria

The operation is considered installed only after the service is enabled, `--doctor` succeeds, one harmless queued documentation task completes, the result is recorded, the worker restarts cleanly, and a stop command reliably halts it. A running process alone is not proof of successful autonomous development.