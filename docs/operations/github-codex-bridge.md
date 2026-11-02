# STREAMIOV GitHub-to-Codex bridge

## Purpose

This is a small, supervised mailbox between the ChatGPT GitHub connector and
the local Codex CLI on the Chromebook. ChatGPT creates or labels a GitHub issue
with the codex-bridge-ready label; the local bridge polls that label, asks the
already-authenticated Codex CLI to work in ~/streamiov, validates changed
paths, runs the complete Python unit-test suite, and publishes a draft pull
request. The issue receives the PR link and status.

This is not a direct connection to the current ChatGPT browser conversation,
does not share a Codex transcript, and does not expose a remote shell. GitHub
issues/comments are the message channel.

## Prerequisites

- Existing ~/streamiov Git checkout with a clean working tree.
- Python 3.10+, Git, GitHub CLI (gh) and Codex CLI installed.
- gh auth status succeeds for the repository owner account.
- Codex is already authenticated locally with codex login.
- The local Git origin remote can push feature branches and create draft PRs.

No Cloudflare Worker, D1 database, API token, new OAuth app, or TikTok setting
is required for this GitHub mailbox pilot.

## First local check

From the repository root:

~~~bash
cd ~/streamiov
gh auth status
codex --version
python scripts/codex_github_bridge.py --once
~~~

The first run creates four repository labels if missing:

- codex-bridge-ready: queued task.
- codex-bridge-in-progress: being processed locally.
- codex-bridge-review: draft PR created; human review required.
- codex-bridge-blocked: stopped safely; inspect the local terminal.

To keep polling while the Chromebook is awake:

~~~bash
python scripts/codex_github_bridge.py --loop --poll-seconds 30
~~~

Press Ctrl-C to stop. This is a foreground pilot; no systemd service is
installed or enabled automatically.

## Queueing work from ChatGPT

1. Create a GitHub issue in schaffrathsascha318-ship-it/streamiov---core.
2. Include a small, testable task and explicit acceptance criteria.
3. Apply the codex-bridge-ready label.
4. The local bridge accepts only open issues authored by OWNER, MEMBER or
   COLLABORATOR and processes at most one task at a time.

The issue title/body are treated as untrusted task data. Do not put credentials,
private data, or secrets in issues.

## Safety and limits

- Codex runs with the workspace-write sandbox; no approval/sandbox bypass flag
  is used.
- The Codex child process does not inherit GitHub, Cloudflare, STREAMIOV,
  AWS/Azure/Google, or common API-key environment variables. Its normal local
  Codex authentication remains necessary to use the model.
- The model is instructed not to access secrets, .env, OAuth data, browser
  profiles, SSH credentials or ~/.codex, and not to deploy, publish, install,
  change credentials, or use GitHub CLI.
- Initial changed-path allowlist is deliberately narrow: ai/, tests/,
  docs/ai-development/, docs/operations/, scripts/agent_bridge/, and the bridge
  script/tests. Studio runtime, Core services, Cloudflare infrastructure,
  gifts, games and production files are not in scope yet.
- Deletions, renames, copies, symlinks, out-of-scope changes, test failures and
  dirty starting workspaces block publication.
- Successful tasks are committed on a new feature branch and pushed as a
  draft PR. No merge, deployment, release, payment, payout or OAuth change is
  performed automatically.
- Failed tasks remain on their local feature branch for inspection. Review or
  clean up that branch manually before retrying.
- This bridge is a pilot, not a security boundary against a fully compromised
  local Codex process. Keep the Chromebook account and repository credentials
  protected.

## Verification

Run the focused tests:

~~~bash
python -m unittest discover -s tests -p 'test_codex_github_bridge.py' -v
~~~

The local end-to-end acceptance test still requires a real queued issue,
successful Codex execution on the Chromebook, and a resulting draft PR.
