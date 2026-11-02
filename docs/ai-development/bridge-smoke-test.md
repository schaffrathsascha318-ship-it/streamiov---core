# Local Codex bridge smoke test

## Purpose

The local GitHub-Codex bridge selects eligible queued issues and runs bounded Codex work in a checked-out STREAMIOV repository. It checks changed paths and local tests before it publishes a draft pull request for human review.

## Phases and evidence

The repository implementation defines these phases: issue selection, a per-issue working branch, Codex execution, changed-path and deletion checks, `git diff --check` and the Python unittest suite, then commit, push, and draft-PR creation. The bridge also updates issue labels and posts status comments as part of that workflow.

For this smoke-test task, the issue text and repository implementation were inspected, and this documentation file was created. **Not tested:** whether the running bridge selected this issue; whether it created a working branch or invoked Codex through the bridge; whether bridge path validation accepted this change; whether the bridge ran its full repository test suite; or whether it committed, pushed, updated GitHub labels/comments, or created a draft PR. No end-to-end bridge run was performed in this session. Those results cannot be inferred from the code or from the local checks below.

## Local checks

- Focused bridge unit tests (`python3 -m unittest tests.test_codex_github_bridge -v`): passed, 13 tests.
- `git diff --check`: passed.

These checks cover the local repository code and this change only. They do not establish that the GitHub-connected workflow or a draft PR works.

## Open prerequisites and blockers

- Bridge publication requires a configured GitHub CLI/repository connection and an `origin` with a fetchable `main` branch. These were not exercised.
- The bridge requires a clean checkout before processing an issue. The implementation stops if it finds existing changes; this documentation task does not establish whether a separate bridge workspace satisfies that condition.
- The workflow requires its configured labels, eligible issue metadata, and available `git`, `gh`, and `codex` executables. Their availability and behavior in the bridge environment are **not tested**.
- The policy requires human review of any resulting draft PR. No merge or deployment is authorized by this smoke test.
