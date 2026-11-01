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
