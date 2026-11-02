# Local GitHub Codex bridge pilot

This runbook covers a foreground, one-shot pilot of the local GitHub Codex bridge. The bridge handles a GitHub issue in a separate, clean task worktree and publishes a draft pull request for human review when the task succeeds.

## Checkouts and workspace

The runner's default workspace is `~/streamiov`. Do not use that default for this pilot. Use a separate Git worktree for the issue, and pass its absolute path explicitly with `--workspace`.

Keep two directories distinct:

- **Control checkout:** the stable checkout containing `scripts/codex_github_bridge.py`. Run the bridge command from this checkout. Keep it on its stable branch while the task runs.
- **Task workspace:** a separate clean Git worktree containing the repository state the issue should modify. The runner checks out or switches branches in this workspace. Because the runner script is in the control checkout, it remains available when the task workspace changes branches.

The selected task workspace must be the root of a Git repository and have a completely clean working tree before processing starts. Resolve the task worktree's absolute path before running the command; do not substitute the control checkout's current directory.

## One-shot invocation

On the Chromebook, use `python3`. Replace the example task-worktree path with the actual absolute path of the separate, clean worktree. Run the command from the stable control checkout:

```sh
cd /absolute/path/to/stable-control-checkout
python3 scripts/codex_github_bridge.py \
  --repo schaffrathsascha318-ship-it/streamiov---core \
  --workspace /absolute/path/to/clean-task-worktree \
  --once
```

The `--workspace` value must name the task worktree, not the control checkout. `--once` processes at most one task and exits. Run it in the foreground so output and failures remain visible; do not background it or configure it as an unattended service.

## Change boundaries and review

The runner's exact changed-path allowlist is:

- `ai/`
- `tests/`
- `docs/ai-development/`
- `docs/operations/`
- `scripts/agent_bridge/`

The allowlist does not include `scripts/codex_github_bridge.py` or `tests/test_codex_github_bridge.py`. Tasks that require changes outside the allowlist cannot be published by this bridge.

If Codex exits successfully without making repository changes, the runner blocks the task. It does not create a draft pull request for a no-change task. Give the task a concrete change to make or review it manually.

For successful tasks, the runner tests, commits, and pushes the changes, then publishes a draft pull request for human review. A draft is not approval: a person must review it. The bridge does not merge, deploy, or release changes.

## Safety and credentials

Review the task and resulting draft before any human decides whether it is ready to merge. Keep the pilot in the foreground, and stop it if its output or requested changes are unexpected. The clean-worktree requirement isolates task changes from other local work; the path allowlist limits which changes the runner may publish.

Use only the credentials already configured for the local bridge and GitHub access. Do not put tokens, passwords, or other secrets in issue text, command-line arguments, or repository files. Keep credentials out of logs and drafts, and follow the existing local credential-handling process if access needs to be configured or refreshed.
