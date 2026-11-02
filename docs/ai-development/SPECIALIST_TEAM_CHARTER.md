# STREAMIOV Specialist Team Charter

Status: implementation proposal for review; this document describes the current shared runtime and does not claim that eight independent AI systems are already running.

## Purpose and operating model

The specialist team is an organizational responsibility map over the eleven existing role profiles in `ai/specialists/registry.py`. The profiles share the configured model/provider runtime. They are not eleven separately trained models, eight separately hosted models, or continuously running agents.

Work is planned through `SpecialistPlanner`, validated by `TaskOrchestrator`, and may be persisted through `SpecialistTaskQueue`. A `SpecialistWorker` claims and executes one queued task at a time through the existing role-scoped agent factory. `worker_service.run_worker_loop` provides a supervised polling loop when explicitly started. GitHub Actions runs only when its configured event/schedule and repository preflight allow it. The local Codex bridge is a separate supervised execution path; it is not a live connection from this document or from an open ChatGPT conversation.

No worker is assumed to be running merely because its role is registered, a task is planned, or a queue exists. A real execution requires a started runner, a configured provider, valid credentials where applicable, and passing verification.

## Team map

The eight teams below are responsibility groups. The mapping intentionally reuses `integration` and `general`; it does not clone roles or create additional model instances.

| # | Team | Existing specialist roles | Mission and accountable output |
|---|---|---|---|
| 1 | Architecture & Development Lead | `core`, `general` | Own shared contracts, orchestration boundaries, architecture decisions, scope clarification, and cross-team handoffs. Output: reviewed architecture notes and bounded task plans. |
| 2 | Cloudflare & Core | `server`, `integration` | Own server-side services, Cloudflare integration contracts, health/monitoring/recovery design, and tested adapters. Output: versioned API contracts, integration tests, and operational runbooks. |
| 3 | Studio & Regie | `studio` | Own the Streamiov Studio, scene control, media interfaces, and device adapters. Output: Studio features with device and scene regression coverage; no OBS dependency. |
| 4 | AI Development | `code` | Implement AI runtime, provider adapters, planner/agent features, and focused engineering tasks within assigned scope. Output: small compatible code changes and tests. |
| 5 | Games Development | `game` | Create original game concepts and gameplay systems; preserve provenance and rights boundaries. Output: playable candidates with separate gameplay, rights, and release evidence. |
| 6 | Gifts & Design | `gifts`, `design` | Own Streamiov-native gift definitions/event mappings, visual systems, overlays, accessibility, and auditable accounting tests. Output: original design specifications/assets and tested gift contracts. |
| 7 | Security & Quality | `testing`, `repair` | Independently test, reproduce defects, perform scoped repairs, and protect security and quality gates. Output: reproducible test reports, regression tests, and minimal fixes. |
| 8 | Integration & Release Coordination | `integration`, `general` | Coordinate cross-team contract compatibility, release readiness evidence, dependency closure, and handoff completeness. Output: integration matrix and release-readiness recommendation; no autonomous publication. |

## Existing specialist directory

These are the eleven registry IDs and their current missions. The registry remains the source of truth; this table is explanatory and must be updated when a role mission changes.

| Role ID | Registry title | Current mission |
|---|---|---|
| `core` | Core Architect | Own shared contracts, orchestration boundaries, and platform architecture. Prefer small, versioned interfaces and preserve module separation. |
| `code` | Software Engineer | Implement focused code changes, maintain compatibility, and add regression tests for the assigned task. |
| `game` | Game Developer | Create original games and gameplay systems. Preserve provenance and rights boundaries; never treat an unlicensed existing game as reusable source material. |
| `design` | Visual Design Specialist | Develop accessible STREAMIOV visual systems, original assets, overlays, and responsive design specifications. |
| `gifts` | Gift Systems Specialist | Develop original STREAMIOV-native gift definitions, event mappings, and auditable accounting tests. Never claim payment or payout execution unless verified. |
| `testing` | Quality Engineer | Design and run reproducible tests, report failures precisely, and add regression coverage. Do not weaken assertions to make a build green. |
| `repair` | Repair Engineer | Diagnose a reproducible defect, make the smallest safe correction, and rerun the relevant regression tests. |
| `integration` | Integration Engineer | Maintain explicit API contracts and connect modules through tested adapters without bypassing platform permissions. |
| `studio` | Studio Engineer | Build the independent STREAMIOV Studio, scene control, media interfaces, and device adapters. Do not introduce an OBS dependency. |
| `server` | Cloud and Operations Engineer | Develop server-side services, deployment definitions, health checks, monitoring, and recovery tests. Never access or change production secrets. |
| `general` | General Coordinator | Clarify task scope, inspect safe project context, and prepare documentation or handoff notes. Delegate implementation to a specialist role. |

## Least-privilege and task boundaries

Team membership never grants filesystem permissions. Every task must satisfy all of these boundaries:

1. The specialist's existing `writable_prefixes` in the registry.
2. The task-specific allowed paths and repository policy.
3. The execution tool's own path, symlink, protected-file, and command restrictions.

The effective write scope is the intersection of those boundaries, never their union. Do not expand registry prefixes to make a team assignment convenient. A handoff to another role must be represented as a new task assigned to that role, not as permission to write outside the current role's scope.

The specialist roles currently have these effective registry prefixes:

| Role | Registry write prefixes |
|---|---|
| `core` | `ai/`, `core/`, `docs/architecture/`, `tests/` |
| `code` | `ai/`, `docs/ai-development/`, `tests/` |
| `game` | `games/`, `ai/specialists/game/`, `docs/games/`, `tests/` |
| `design` | `assets/`, `overlays/`, `docs/design/`, `tests/` |
| `gifts` | `gifts/`, `ai/buildbot/`, `ai/runtime/`, `docs/gifts/`, `tests/` |
| `testing` | `tests/`, `docs/testing/` |
| `repair` | `ai/`, `core/`, `tests/`, `docs/repairs/` |
| `integration` | `core/`, `infrastructure/`, `tests/`, `docs/integration/` |
| `studio` | `app/studio/`, `tests/`, `docs/studio/` |
| `server` | `core/`, `infrastructure/`, `tests/`, `docs/server/` |
| `general` | `docs/` |

For this charter task, the issue additionally restricts changes to `ai/`, `tests/`, and `docs/ai-development/`. This PR changes only tests and documentation; it does not alter registry permissions.

## Mission ownership and handoffs

- **Architecture → specialist:** `core` or `general` defines the contract, acceptance criteria, dependencies, and permitted paths before delegating.
- **Cloudflare/Core ↔ Studio/AI/Games/Gifts:** `integration` owns the interface contract and compatibility evidence; the implementation remains with the domain specialist.
- **Implementation → Security/Quality:** the implementing role supplies changed paths, design assumptions, test commands, and known risks. `testing` independently verifies behavior; `repair` receives a reproducible defect and returns a minimal fix for retest.
- **Domain teams → Integration/Release:** teams provide passing test evidence, compatibility notes, provenance/licence records where relevant, security/privacy review, and unresolved risks.
- **Release coordination → human owner:** `general` prepares the readiness summary. Production deployment, external publication, irreversible operations, financial actions, credential changes, and legal approvals remain explicit human decisions.

A handoff is complete only when it includes: task ID, source role, receiving role, goal, relevant contract/version, exact changed paths, dependencies, verification performed, remaining risks, and a clear next action. The receiving role must reject incomplete or out-of-scope work rather than infer missing authorization.

## Planning, queueing, and execution

1. The planner may select only registered specialist IDs. The planner output must be strict JSON and pass schema, task-count, identifier, dependency, role, and DAG validation before it is accepted.
2. The orchestrator validates the entire plan before executing any task. Unknown roles, duplicate IDs/dependencies, missing dependencies, malformed tasks, and dependency cycles fail closed.
3. The durable queue reuses orchestrator validation before inserting tasks. A queued task is not evidence that a worker has claimed or executed it.
4. A worker claims one task under a bounded lease, invokes the role-scoped agent factory, and records success/failure. Expired leases and failed prerequisites are handled conservatively.
5. The supervised worker loop runs only when explicitly started by its caller or process supervisor. The repository does not automatically enable a permanent worker service.
6. GitHub Actions and the local Codex bridge are distinct execution mechanisms. Their credentials, permissions, and start conditions remain independently controlled.

## Definition of done

A team task is complete only when:

- The assigned role is registered and its prompt contains its mission and write boundaries.
- All changed paths are inside the intersection of role, task, and repository permissions.
- The relevant automated tests pass without weakening existing assertions.
- The task records what was actually run and distinguishes mocks from real services.
- Cross-team contracts and dependencies are verified by the receiving team.
- Security, privacy, rights, and provenance requirements relevant to the task are addressed.
- Remaining risks and unverified production/staging steps are stated explicitly.

A green unit-test suite does not prove a live Cloudflare connection, real D1 behavior, TikTok authorization, active background agents, production deployment, or release readiness. Those require separate environment-specific checks and approvals.

## Explicit non-goals

This charter does not create separate models, train model weights, start a permanent agent fleet, expand write scopes, change GitHub workflow permissions, access secrets, provision Cloudflare resources, change TikTok OAuth/security, deploy production services, publish games, or merge code.
