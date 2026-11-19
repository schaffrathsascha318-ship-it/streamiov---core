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
