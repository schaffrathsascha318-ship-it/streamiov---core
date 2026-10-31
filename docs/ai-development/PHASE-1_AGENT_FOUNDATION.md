# Streamiov Phase 1 — local development agent foundation

## Architecture inventory (2026-10-31)

The inspected base ref is `streamiov-build-setup-clean`. Its tracked `ai/` tree contains an archived rescue copy at `ai/core/streamiov_ai.py.rescue-20261008-012502`, buildbot backup material, and runtime task/approval/log/report data. It does not contain active implementations under `ai/providers/` or `ai/selfhosted/`; the runtime executor exists only as `executor.py.pre-autonomy-backup`. These artifacts are historical evidence, not proof of a functioning autonomous developer agent. Existing records were preserved.

## Implemented

- Replaceable provider contract and two local adapters: Ollama and local OpenAI-compatible HTTP.
- Providers accept only plain HTTP loopback endpoints; there are no cloud providers, API keys, paid fallbacks, model weights, or automatic downloads.
- JSON tool loop with bounded steps and fail-closed parsing.
- File reads and create-only writes under AI, documentation, and test directories; arbitrary shell is not exposed.
- Secret-like paths, OAuth paths, environment files, symlinks, path traversal and build/dependency directories are denied.
- Only one fixed unittest command is allowed. Existing files cannot be overwritten.

## Local setup

Install Python 3.10+ and a local model runtime separately. With Ollama, start its service and install a suitable model yourself, for example `ollama pull qwen2.5-coder:7b`. Hardware requirements vary.

```bash
STREAMIOV_MODEL_PROVIDER=ollama STREAMIOV_MODEL=qwen2.5-coder:7b python -c 'from ai.providers.local_http import provider_from_env; from ai.core.agent import DevelopmentAgent; print(DevelopmentAgent(provider_from_env(), ".").run("Describe the AI architecture"))'
```

For a local OpenAI-compatible server set `STREAMIOV_MODEL_PROVIDER=openai-compatible-local`, `STREAMIOV_MODEL`, and `STREAMIOV_MODEL_URL=http://127.0.0.1:8000/v1`.

Run tests with `python -m unittest discover -s tests -v`.

## Verification status

This GitHub editing environment does not expose a project shell or a local model runtime. No local inference or passing test run is claimed. A pull-request workflow runs the unit tests on GitHub Actions. This is a guarded foundation, not yet a continuously running autonomous service. No production deployment is performed.
