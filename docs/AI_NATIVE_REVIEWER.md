# Streamiov Native Independent Reviewer

Streamiov includes a provider-free review engine at `ai/review/independent_reviewer.py`.

## Design guarantees

- No model endpoint, third-party review API, external network request, or external service is used.
- Review is read-only: it inspects Git refs and diff contents and never modifies the reviewed tree.
- The rule set detects credential signatures, risky execution/transport patterns, protected control-plane changes, Python syntax errors, and source changes without accompanying tests.
- Only a fixed Python unittest command may be run by the optional test mode. The patch cannot supply a shell command.
- Reports are machine-readable JSON with severity counts, exact changed paths, findings, and a deterministic decision.

## Use

```sh
python -m ai.review.independent_reviewer --base main --head HEAD
python -m ai.review.independent_reviewer --base main --head HEAD --run-tests
```

Decisions:

- `pass`: no findings.
- `pass_with_warnings`: medium/low findings only.
- `needs_attention`: protected or otherwise high-risk changes need a dedicated policy review.
- `reject`: critical findings or failed/timed-out tests.

This first version is deliberately deterministic, not an LLM pretending to be an independent reviewer. It provides reproducible local checks without vendor dependence. Its findings supplement, but do not replace, CI, security review, or external platform authorization.

## AI Chief integration

The continuous mission engine runs this reviewer immediately before accepting a planner's completion proposal, after the separate testing-specialist evidence report passes. The autonomous runner configures the review against the checked-out `main` ref and the exact current `HEAD` commit.

- The reviewer report records immutable base/head commit SHAs and is persisted in the encrypted SQLite mission checkpoint.
- A `reject` or `needs_attention` decision prevents mission completion and creates a repair/evidence task for the AI Chief.
- Repair instructions explicitly forbid editing protected workflows, deployment, provider, OAuth, credential, and permission-control paths.
- The reviewer does not write files, run patch-supplied commands, call external services, approve releases, merge pull requests, or deploy.
- Medium/low findings remain visible as warnings; critical/high findings block completion.
- If the review cannot run or its Git evidence is unavailable, completion is not accepted.

This is a deterministic, local policy reviewer, not a claim of human-level semantic review. It supplements the independent testing specialist and repository CI. The first integration release must itself pass its own CI and bootstrap safety review.

## Trust-anchor protection

The autonomous agent cannot modify `ai/review/`, `ai/core/agent.py`, `ai/runtime/continuous_engine.py`, `ai/runtime/project_tools.py`, or `ai/providers/`, even in full-project development mode. The workflow independently rejects changes to those paths from autonomous mission branches. This keeps the reviewer, completion gate, permission enforcement, and existing provider boundary outside the developer agent's self-approval loop. The CLI and ordinary agent implementation remain eligible for controlled self-improvement.

## Architecture and provider policy

The reviewer also flags new imports, package references, and endpoints for unapproved third-party AI providers. It rejects adapter/integration paths for OBS, Twitch, YouTube, Kick, and Facebook; the supported external LIVE adapter remains TikTok. These are local static checks and do not call any of those providers or platforms.

## Pull-request review

The `.github/workflows/native-reviewer.yml` check uses `pull_request_target` with explicit read-only permissions, so GitHub runs the workflow from the trusted base branch. It checks out the base SHA and runs only the reviewer code from that revision. It fetches the PR head into Git's object database but never checks out or executes the untrusted PR source. The job has read-only repository permissions, does not run patch-supplied tests or commands, and publishes the structured review report to the Actions summary. No AI/model provider or external review service is called.
