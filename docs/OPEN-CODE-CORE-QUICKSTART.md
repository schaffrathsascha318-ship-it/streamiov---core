# OpenCode Core — self-hosted quick start

OpenCode Core is a project-agnostic, self-hosted worker for software-development tasks. It is designed to run against a repository you choose, with a persistent task queue, bounded parallel workers, specialist roles, and configurable model providers.

It is not a hosted multi-tenant service in this release. Each individual or team should run a separate installation with its own workspace, queue database, provider credentials, and server account. Do not share one writable workspace between unrelated customers. Do not expose the worker CLI or its database to the public internet.

## Requirements

- Python 3.10+ for direct installation, or Docker Engine with Docker Compose.
- A model endpoint you are authorized to use: Ollama, an OpenAI-compatible local endpoint, or the authenticated Cloudflare Workers AI gateway adapter.
- A dedicated project checkout/workspace. Back it up and use version control before allowing automated edits.

## Install from a checkout

```sh
git clone https://github.com/schaffrathsascha318-ship-it/streamiov---core.git
cd streamiov---core
git switch feat/opencode-core-foundation
python -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install .
opencode-core --help
```

For Windows PowerShell, activate with `.venv\\Scripts\\Activate.ps1`.

## Configure a model

Copy `.env.example` to `.env` and set the provider details. The CLI reads `OPENCODE_*` variables first. Existing `STREAMIOV_*` names remain supported for backwards compatibility.

Supported primary providers:

- `ollama`: `OPENCODE_MODEL` and `OPENCODE_MODEL_URL`.
- `openai-compatible-local`: `OPENCODE_MODEL` and `OPENCODE_MODEL_URL`.
- `cloudflare-workers-ai`: `OPENCODE_MODEL_URL` (your HTTPS workers.dev gateway URL) and `OPENCODE_AI_WORKER_TOKEN`.

An optional `OPENCODE_FALLBACK_PROVIDER` can select one separately configured fallback. Fallback requires its own endpoint and credentials. It does not bypass provider quotas or guarantee capacity.

Never commit `.env`, tokens, private keys, or provider credentials.

## Point it at your project

Use `--project-root` to select the repository. Use repeated `--write-scope` options to name the directories the agent may create or edit. These scopes replace the built-in Streamiov-specific role scopes for that run; protected paths such as `.git`, `.env*`, secrets, OAuth data, and key files remain blocked.

Example for a typical Python or JavaScript project:

```sh
opencode-core \
  --project-root /path/to/your/project \
  --specialist code \
  --write-scope src/ \
  --write-scope app/ \
  --write-scope lib/ \
  --write-scope tests/ \
  --write-scope docs/ \
  --task "Add a health-check endpoint and tests"
```

Only grant scopes that you are comfortable allowing the agent to change. The agent does not receive arbitrary shell access; its test command is currently the fixed Python unittest discovery command. Node, Rust, Go, Java, mobile, and platform-specific test adapters are not included yet.

## Queue and parallel workers

Create a task without running it immediately:

```sh
opencode-core --project-root /path/to/project --queue-db /var/lib/opencode-core/queue.sqlite3 --specialist code --enqueue --task "Add a health endpoint"
```

Or ask the planner to split a larger goal into a dependency-aware specialist plan:

```sh
opencode-core --queue-db /var/lib/opencode-core/queue.sqlite3 --plan-and-enqueue --task "Review and improve the project test coverage"
```

Run the persistent worker pool:

```sh
opencode-core \
  --worker-loop \
  --project-root /path/to/project \
  --queue-db /var/lib/opencode-core/queue.sqlite3 \
  --worker-id team-core \
  --workers 2 \
  --write-scope src/ \
  --write-scope tests/ \
  --write-scope docs/
```

The SQLite database is the source of truth for queued work. Keep it on durable storage, restrict its filesystem permissions, and back it up. For production-like use, run under a dedicated unprivileged OS account and a process supervisor. A systemd template is provided at `infrastructure/systemd/streamiov-opencode-core.service`; review and adapt paths, users, permissions, and environment settings before installing it.

## Docker Compose

```sh
mkdir -p workspace
cp .env.example .env
# Edit .env with your own model endpoint and token, if required.
docker compose up --build -d
```

Place the repository you want the agent to work on inside `workspace/`. The example Compose file grants write access only to `src/`, `app/`, `lib/`, `tests/`, and `docs/`. Edit those scopes to match your project before starting the service.

Queue a task into the same persistent database:

```sh
docker compose run --rm opencode-core \
  --project-root /workspace \
  --queue-db /state/queue.sqlite3 \
  --specialist code \
  --enqueue \
  --task "Add a small health endpoint and tests"
```

View logs and stop the service:

```sh
docker compose logs -f opencode-core
docker compose down
```

The example container runs as a non-root user, drops Linux capabilities, and stores queue state in a named volume. The mounted workspace is still writable by the container user; use a dedicated checkout and review its diffs.

## Isolation and trust model

- **One installation per person or team.** This release has no user accounts, tenant API, web dashboard, or per-user authorization layer.
- Give each installation its own server account, workspace mount, database, model credentials, and backup policy.
- Never mount a home directory, SSH directory, production secrets directory, or unrelated customer workspaces.
- The agent can read project files in its workspace, except for blocked secret-like paths. Do not put secrets in the workspace.
- The model provider receives task prompts and relevant file contents. Use only a provider whose data handling terms you accept.
- Automated edits are not automatically merged or deployed. Review diffs, run tests, and keep human approval for releases and production changes.
- A model fallback is a reliability feature, not an unlimited-quota mechanism.
- SQLite queue leases support restart recovery, but exactly-once execution and all external side effects are not guaranteed.

## Current maturity

This is an early self-hosting foundation, not a production-ready public SaaS. Before offering a shared hosted service, implement and independently review tenant authentication, authorization, workspace isolation, per-tenant queues and secrets, rate/cost controls, audit logs, abuse protections, backup/restore, and incident response. Run the full test suite and a security review before exposing it to untrusted users.

## Licensing

The repository does not yet contain an approved software license. Public visibility on GitHub does not by itself grant permission to redistribute, modify, or commercially offer the software. The project owner must choose and add a license before public third-party reuse is authorized.
