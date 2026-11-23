# Streamiov AI Chief – persistent project supervisor

The local service is the long-running development runner for the complete Streamiov project. It uses the existing mission engine and its SQLite database, then starts the next distinct mission only after the current mission passes the independent testing-specialist completion gate.

## Configure the provider

Keep provider credentials only in the private local file:

`~/.config/streamiov/ai-worker.env`

Never commit that file or copy tokens into `ai-chief.env`.

## Start the project supervisor

From the repository root:

```bash
bash scripts/ai/run-chief-mission.sh
```

The runner uses `.streamiov/ai-missions.sqlite3` by default and keeps its project goal in the same database. It works across multiple verified missions, resumes an active mission after interruption, and prevents concurrent supervisor processes with a renewable SQLite lease.

Optional private configuration in `~/.config/streamiov/ai-chief.env`:

```bash
# Optional project-goal override:
# STREAMIOV_AI_PROJECT_GOAL="Continue building and verifying the complete Streamiov platform."
# Optional: adopt an existing mission on the first supervisor start.
STREAMIOV_AI_MISSION_ID=
# Optional database override:
# STREAMIOV_AI_MISSION_DB=/absolute/path/to/.streamiov/ai-missions.sqlite3
```

If `STREAMIOV_AI_MISSION_ID` is set and no supervisor state exists yet, the supervisor adopts that mission instead of discarding its checkpoint. Once supervisor state exists, it remains authoritative and is not overwritten by later environment changes.

## Configure auto-start

On systems with a working systemd user manager:

```bash
bash scripts/ai/install-user-service.sh
```

The installer creates a private configuration template if needed and enables the service. It does not modify production services or install an unmanaged background process.

On systems without a user manager, start the runner manually with `bash scripts/ai/run-chief-mission.sh`.

## Operations

```bash
systemctl --user status streamiov-ai-chief.service
journalctl --user -u streamiov-ai-chief.service -f
python3 -m ai --jason-status
```

Stop and disable auto-start:

```bash
systemctl --user disable --now streamiov-ai-chief.service
rm -f ~/.config/systemd/user/streamiov-ai-chief.service
systemctl --user daemon-reload
```

## Safety and recovery

- Mission plans, task outcomes, retry state, supervisor progress, and leases are persisted in SQLite.
- The local service reuses the existing mission database; it does not delete or replace it.
- A process restart resumes the active mission. A verified mission is recorded before the next mission is created.
- The supervisor's renewable lease prevents two local service instances from executing the same project goal concurrently.
- Full-project development still respects protected secrets, GitHub workflow/runner controls, deployment configuration, credential boundaries, and the existing sandbox rules.
- The Python file tool prefers Linux `setpriv`; when the environment cannot drop privileges, safe execution is blocked rather than silently rerun unsandboxed.
- Production deployment, public release, OAuth/security changes, and irreversible external actions remain behind their existing safeguards.
