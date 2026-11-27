# Local Codex bridge smoke test

## Purpose

The local GitHub-Codex bridge selects eligible queued issues and runs bounded Codex work in a checked-out STREAMIOV repository. It checks changed paths and local tests before publishing a draft pull request for human review.

## Phases and observed evidence

This smoke test ran on the Chromebook Linux (Penguin) environment, architecture aarch64, using the isolated `~/.codex-streamiov-bridge` login.

The bridge processed Issue #116 in this order:

1. Selected the eligible issue from the `codex-bridge-ready` queue.
2. Created working branch `codex-bridge/issue-116-1793606499`.
3. Ran Codex with the isolated login.
4. Accepted only the requested documentation path after changed-path validation.
5. Passed `git diff --check` and the repository Python unittest suite.
6. Committed and pushed the change, then created Draft PR #119.
7. Updated the issue label to `codex-bridge-review`.

GitHub reports PR #119 as merged on 2026-11-22. It was opened as a draft and mergeable during the bridge run, and Secret Scanning completed successfully. The bridge run's `review` result demonstrates that its local path checks and full unittest gate passed; this document does not infer a test count from that result. The later merge is separate from the bridge smoke test itself.

## What this verifies

This run verifies the local bridge's separate-login preflight, issue selection, working-branch setup, Codex execution, changed-path checks, local test gate, commit/push sequence, draft-PR creation, and issue status update for this documentation-only task.

This does not verify other tasks, product runtime behavior, resistance to a compromised Codex process, or merge/deployment behavior. No merge or deployment was performed.

## Remaining review

PR #119 has already been merged, so no merge action remains for it. The original issue #116 is still open and labeled `codex-bridge-review`; the bridge behaviour itself still needs separate human acceptance.
