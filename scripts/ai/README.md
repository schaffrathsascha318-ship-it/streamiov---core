# Streamiov AI Chief – persistent mission runner

This service is a **local development runner**. It does not deploy or publish production changes and is not a production hosting service.

## Create a mission

From the repository root, with the Streamiov AI Worker environment already configured:

```bash
python3 -m ai --mission-create --task "Finish and verify the existing Streamiov AI Chief Developer."
```

Copy the returned `mission_id`. The mission database defaults to `.streamiov/ai-missions.sqlite3`.

## Configure auto-start

Create or edit the private local file `~/.config/streamiov/ai-chief.env`:

```bash
mkdir -p ~/.config/streamiov
chmod 700 ~/.config/streamiov
nano ~/.config/streamiov/ai-chief.env
```

Set the mission ID (do not put API tokens in this file):

```bash
STREAMIOV_AI_MISSION_ID=PASTE_THE_RETURNED_MISSION_ID
```

The runner also sources the existing private `~/.config/streamiov/ai-worker.env` file if present. Neither file belongs in Git.

Install and start the user service:

```bash
bash scripts/ai/install-user-service.sh
```

The installer requires a working systemd user manager. It does not silently fall back to an unmanaged background process. On systems without a user manager, run the mission in a terminal:

```bash
bash scripts/ai/run-chief-mission.sh
```

## Operations

```bash
systemctl --user status streamiov-ai-chief.service
journalctl --user -u streamiov-ai-chief.service -f
python3 -m ai --mission-status MISSION_ID
```

Stop and disable auto-start:

```bash
systemctl --user disable --now streamiov-ai-chief.service
rm -f ~/.config/systemd/user/streamiov-ai-chief.service
systemctl --user daemon-reload
```

The mission engine stores plans, task outcomes, retries and leases in SQLite. Agent checkpoints store conversation history, pending tool batches, completed tool results and a final result until the mission engine records task success. After a process interruption, completed tool actions are not replayed; an action interrupted between execution and its checkpoint write may be attempted again, so the tool layer must continue to enforce safe/idempotent behavior.

Provider request sizes and individual model responses remain subject to the provider's natural limits. The agent continues across multiple turns and the mission engine chunks work into planning batches instead of treating those protocol limits as a mission-wide task or runtime ceiling.

The Python file tool prefers Linux `setpriv`: it drops to UID/GID 65534, clears supplementary groups, sets `no-new-privs`, and passes a clean environment without the developer's tokens. This is not a complete network or syscall sandbox; do not run untrusted third-party Python source with it. On local systems where `setpriv` is unavailable, execution is disabled unless the user explicitly sets `STREAMIOV_AI_ALLOW_UNSANDBOXED_PYTHON=1` in the private runtime environment. GitHub-hosted CI has a narrowly scoped fallback because its disposable runner may forbid UID changes and contains no user credentials.

The service runner does not authorize production deployment, public release, OAuth/security changes, or irreversible external actions. Those remain approval-gated.
