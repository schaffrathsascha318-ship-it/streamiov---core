# StreamioV local AI specialists

## Design

The roles share one locally hosted model; each invocation gets a distinct task contract and an enforced write allowlist. A role cannot expand its own permissions. Exact-match edits are required for existing files, new-file creation cannot overwrite an existing file, shell access is limited to one fixed unit-test command, and network, credentials, deployments, publishing, and purchases are outside the agent tools.

Choose a role with `python3 -m ai --role <role> --task "..."`. The default is `software`.

| Role | Focus | Writable project areas |
| --- | --- | --- |
| `software` | General code and architecture | `ai/`, `docs/ai-development/`, `tests/` |
| `studio` | Studio/Regie and local media | `dist/streamiov-studio-app/`, `studio/`, `tests/`, `docs/` |
| `games` | Original multi-genre games and branding | `games/`, `tests/`, `docs/` |
| `music_rights` | Local music catalogue and permission evidence | `modules/music/`, `data/music/`, `tests/`, `docs/` |
| `moderation` | Content labels and consistent conduct policy | `modules/music/`, `data/music/`, `tests/`, `docs/` |
| `gifts` | Free StreamioV effects and external payment boundaries | `dist/streamiov-studio-app/`, `ai/buildbot/`, `tests/`, `docs/` |
| `design` | Product design and original identity | `games/branding/`, `dist/streamiov-homepage-worker/public/assets/`, `tests/`, `docs/` |
| `integration` | Least-privilege documented platform adapters | `core/integration/`, `tests/`, `docs/` |
| `quality` | Test design and evidence review | `tests/`, `docs/` |

Reads are limited to safe project files: environment files, secrets, OAuth data, credentials, generated dependency trees, and private keys remain blocked. Every role has the same fixed unit-test command and maximum task/runtime limits; the `games` role also has a dedicated no-argument `run_game_checks` action that discovers local game manifests, runs the fixed package audit, and executes only Python/Node test files under those game projects. It cannot accept shell commands or arbitrary paths through that action. Roles are task contracts over one shared model, not separate model instances.

## Current runtime evidence

On 2026-11-02, `python3 -m ai --doctor` selected the default `ollama` provider and model `qwen2.5-coder:7b`. With the read-only check permitted to reach loopback, it reported `reachable: false`, `model_available: false`, and connection refused at `127.0.0.1:11434`. Neither `ollama`, `llama-server`, nor `llama-cli` is installed on that machine. The environment reports 2.7 GiB RAM with about 213 MiB available. Therefore the specialist routing and access boundaries are implemented and unit-tested, but a real inference run is **not verified** on this host. Do not install or download a multi-gigabyte model here; run the setup on an already-owned capable computer and record its model license, disk/RAM requirements, and `--doctor` output first.

Unit tests use fake providers for routing and a local loopback HTTP test server for provider request behavior. They prove code paths and boundaries, not model quality, hardware capacity, or an actual specialist task run.
