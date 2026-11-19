# AI Chief Mission Recovery

This note records the operational contract for persistent Streamiov AI Chief missions.

## Specialist action protocol

- A specialist response must be one JSON action object, a JSON array of action objects, or the exact final-result object.
- The complete action batch is parsed and schema-validated before the first tool is invoked.
- Syntax and schema correction is bounded to three attempts per runner execution slice.
- The cumulative correction count is retained in the encrypted SQLite checkpoint for diagnostics, but it is not a lifetime cutoff. A later slice may correct a new response after earlier slices failed.
- Invalid or mixed final/tool batches are rejected before side effects.

## Interrupted actions

- The action intent is persisted before invoking a tool.
- The in-flight action index, cursor, results, and checkpoint version are persisted.
- If the process stops while a side effect may be in flight, the action is treated as having an unknown outcome.
- Recovery never blindly replays that action. The specialist receives an untrusted recovery notice and must inspect current project state with read-only tools before reconciling.
- Existing durable mission and per-agent checkpoint identifiers are retained across runner slices.

## Provider quota exhaustion

- Cloudflare Workers AI `daily_ai_limit_reached` is treated as a daily quota condition, not a transient one-minute outage.
- Task and planner retry timestamps are persisted for six hours initially, increasing to at most 24 hours if the next daily window is still unavailable.
- When only long-backoff work remains, the hosted runner returns its current mission snapshot early so the encrypted checkpoint can be saved without idling for the full execution window.
- No paid inference fallback is enabled. The mission remains resumable when the configured free quota becomes available again.

## Evidence required before mission completion

A successful GitHub Actions job is not mission completion. The original mission must demonstrate:

1. The same mission ID and authenticated encrypted checkpoint are restored.
2. Real specialist execution produces a relevant source change.
3. Relevant automated tests pass.
4. A separate testing specialist supplies a schema-valid independent verification report with concrete evidence and no unresolved findings.
5. A later runner slice restores the same mission and its per-agent checkpoints.
6. The result is documented with commit IDs, test run IDs, and checkpoint evidence.

The original mission `streamiov-issue-145` remains the required continuation target after the recovery stack is reviewed and integrated. The repair issue's separate diagnostic mission is not a replacement for it.
