# Streamiov Phase 1 — local development agent foundation

## Architecture inventory (2026-10-31)

The inspected base ref is `streamiov-build-setup-clean`. Its tracked `ai/` tree contains an archived rescue copy at `ai/core/streamiov_ai.py.rescue-20261008-012502`, buildbot backup material, and runtime task/approval/log/report data. It does not contain active implementations under `ai/selfhosted/`; the previous runtime executor and Wunschbox entrypoint exist only as `.pre-autonomy-backup` files. These artifacts are historical evidence, not proof of a functioning autonomous developer agent. Existing records were preserved.

## Implemented foundation

- Replaceable provider contract and two local adapters: Ollama and local OpenAI-compatible HTTP.
- Providers accept only credential-free plain HTTP loopback endpoints; URLs with credentials, query tokens, remote hosts, or malformed ports are rejected. Responses must contain non-empty text in the expected Ollama or OpenAI-compatible shape. There are no cloud providers, API keys, paid fallbacks, model weights, or automatic downloads.
- JSON tool loop with bounded steps and fail-closed parsing.
- File reads and create-only writes under AI, documentation, and test directories.
- Exact-match editing of one unique text section in an existing file. Missing or duplicate matches fail without changing the file.
- Secret-like paths, OAuth paths, environment files, symlinks, path traversal and build/dependency directories are denied.
- Only one fixed unittest command is allowed. Existing files cannot be overwritten wholesale.
- The CLI exits with a concise error if the local model endpoint is unavailable or configuration is invalid. It does not download models or fall back to a cloud service.

## Start the agent

From the repository root, start the agent through its CLI:

```bash
STREAMIOV_MODEL_PROVIDER=ollama \
STREAMIOV_MODEL=qwen2.5-coder:7b \
python -m ai --project-root . --max-steps 12 --task "Describe the AI architecture"
```

## Local setup

Install Python 3.10+ and a local model runtime separately. With Ollama, start its service and install a suitable model yourself, for example `ollama pull qwen2.5-coder:7b`. Hardware requirements vary. The agent does not fetch model weights.

```bash
STREAMIOV_MODEL_PROVIDER=ollama STREAMIOV_MODEL=qwen2.5-coder:7b python -m ai --project-root . --max-steps 12 --task "Inspect the AI architecture"
python -m unittest discover -s tests -v
```

For a local OpenAI-compatible server set `STREAMIOV_MODEL_PROVIDER=openai-compatible-local`, `STREAMIOV_MODEL`, and `STREAMIOV_MODEL_URL=http://127.0.0.1:8000/v1`.

## Verification status

Unit tests use a deterministic fake provider to prove that the agent loop performs a real scoped file edit. Local HTTP integration tests also start a temporary loopback server and verify both provider request/response protocols, malformed responses, environment selection, and URL restrictions. These tests verify transport and orchestration, not model intelligence. GitHub Actions runs the repository unit tests and the Studio media smoke test. A real local model inference run still requires an Ollama or compatible model server on a user's machine. No continuously running cloud agent, production deployment, or paid inference is claimed.
