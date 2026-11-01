# STREAMIOV AI specialist runtime

The shared model/provider layer now supports explicit specialist roles with separate missions and enforced write scopes.

## Roles

`core`, `code`, `game`, `design`, `gifts`, `testing`, `repair`, `integration`, `studio`, `server`, and `general`.

Run one bounded agent task with a role:

```bash
python -m ai --specialist game --project-root . --max-steps 12 --task "Create an original game prototype"
```

The default role is `code`. Provider selection remains shared and is configured through the existing provider environment variables. A role is a permissioned configuration, not a separately trained model or a continuously running process.

## Dependency-aware task plans

`ai.core.orchestrator.TaskOrchestrator` accepts a bounded list of `SpecialistTask` records. It validates all roles and dependencies before execution, rejects missing dependencies and cycles, runs ready tasks in stable dependency order, and skips tasks whose dependencies failed. Independent tasks continue after an unrelated failure.

Example:

```python
from ai.core.agent import DevelopmentAgent
from ai.core.orchestrator import SpecialistTask, TaskOrchestrator
from ai.providers.local_http import provider_from_env

provider = provider_from_env()
runner = TaskOrchestrator(
    lambda role: DevelopmentAgent(provider, ".", specialist=role),
    max_tasks=12,
)
results = runner.run([
    SpecialistTask("contract", "core", "Define the event contract"),
    SpecialistTask("tests", "testing", "Add contract tests", ("contract",)),
    SpecialistTask("studio", "studio", "Integrate the contract", ("contract", "tests")),
])
for result in results:
    print(result.task_id, result.status, result.error or result.result)
```

This is a synchronous, in-process plan runner. It is not yet a persistent queue, background daemon, autonomous task planner, or distributed worker system. Results exist in the caller's process; persistence, retries, cancellation, cross-process locking, and durable audit storage remain future work.

## Safety

- Each specialist's file-write scope is enforced by `ProjectTools`, not only by its prompt.
- Existing protected-path, symlink, size, and fixed-test-command restrictions remain in force.
- The runner validates the complete dependency graph before starting any task.
- Failed dependencies block their dependants, while unrelated tasks may continue.
- No arbitrary shell, credential access, OAuth mutation, payment action, or production deployment is provided by this layer.

## Persistent queue CLI

Queue a task without loading a model provider:

```bash
python -m ai --enqueue --queue-db data/ai-tasks.sqlite3 --specialist game --task "Build an original game prototype"
```

Execute at most one queued task and exit:

```bash
python -m ai --worker-once --queue-db data/ai-tasks.sqlite3 --worker-id studio-worker
```

An idle worker exits cleanly without loading a model. A worker claims one task with a time-limited lease, invokes the selected role through the shared provider, and records success or failure. Failed tasks are retried only within their configured retry budget. Run the one-shot command from a supervisor or scheduler if repeated processing is desired; this repository does not yet install or enable an always-on service automatically.

## Supervised worker process

Run a worker loop under a process supervisor:

```bash
python -m ai --worker-loop --queue-db data/ai-tasks.sqlite3 --worker-id streamiov-worker-01 --project-root . --poll-seconds 5
```

The loop processes tasks until it receives SIGINT/SIGTERM. `--max-tasks N` provides a bounded run for maintenance/testing; zero means supervisor-controlled. Each active task renews its lease while the model is working. Expired leases cannot be used to complete or fail a task.

An example hardened systemd unit is provided at `infrastructure/systemd/streamiov-ai-worker.service.example`. It is deliberately not enabled by CI and is not a production deployment. Before installing it, provision a dedicated low-privilege `streamiov` user, review the filesystem paths and write access, install the project/virtual environment, configure the provider in `/etc/streamiov/ai-worker.env`, and keep that environment file outside Git with restrictive permissions. Do not place real tokens in the repository or unit file.

The worker still needs an available configured provider and model. Local Ollama requires a local model runtime on the host. The authenticated Cloudflare Workers AI gateway must be provisioned separately and can stop when its free allocation is exhausted; no paid fallback is performed. A running service on a real cloud host remains a separate deployment and operations acceptance test.

## Core AI planning and specialist assignment

Ask Core AI to split a goal into a validated specialist plan and enqueue it:

```bash
python -m ai --plan-and-enqueue --queue-db data/ai-tasks.sqlite3 --task "Build and test a new STREAMIOV feature"
```

The planner returns a strict JSON task graph. The runtime validates role names, task limits, identifiers, dependencies and cycles before persisting anything. Plan IDs are namespaced to avoid collisions between separate plans. The planner does not execute tasks itself; supervised workers claim them through the queue. Invalid or ambiguous model output is rejected rather than guessed.
