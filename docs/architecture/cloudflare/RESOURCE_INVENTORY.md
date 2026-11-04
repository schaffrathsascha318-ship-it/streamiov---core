# Cloudflare resource inventory — baseline

**Inventory date:** 2026-11-02  
**Status:** Partial; account identity verified, resource discovery blocked by missing read scopes  
**Account:** `Schaffrathsascha318@gmail.com's Account`  
**Account ID:** `d6729e21971b73a3138802be1c7518e8`  
**Evidence source:** Connected Cloudflare API session; read-only GET requests only

> This document records observed facts and access blockers. An inaccessible resource is **unknown**, not absent. No resource configuration, secret value, DNS record, database row, or production deployment was changed during this inventory.

## 1. Confirmed account access

| Check | Result | Evidence |
|---|---|---|
| Authenticated Cloudflare identity | Available | `whoami` returned the connected profile `schaffrathsascha318@gmail.com` |
| Account list | Available | `GET /accounts` returned the account listed above |
| Account-level resource inventory | Blocked | Resource endpoints below returned authorization/authentication errors |

## 2. Resource inventory status

| Resource class | Read endpoint attempted | Result | Required least-privilege read scope |
|---|---|---|---|
| Workers scripts | `GET /accounts/{account_id}/workers/scripts` | Blocked (403; endpoint reported an empty-list ambiguity and refused to treat it as an empty account) | `workers-scripts.read` |
| D1 databases | `GET /accounts/{account_id}/d1/database` | Blocked (401) | `d1.read` |
| R2 buckets | `GET /accounts/{account_id}/r2/buckets` | Blocked (403) | `workers-r2.read` |
| Workers KV namespaces | `GET /accounts/{account_id}/storage/kv/namespaces` | Blocked (401) | `workers-kv-storage.read` |
| Pages projects | `GET /accounts/{account_id}/pages/projects` | Blocked (403) | `page.read` |
| Durable Objects namespaces | `GET /accounts/{account_id}/workers/durable_objects/namespaces` | Blocked (403) | Endpoint reported Workers Scripts permission alternatives; retry with `workers-scripts.read` |
| Queues | `GET /accounts/{account_id}/queues` | Blocked (403) | `queues.read` |
| Vectorize indexes | `GET /accounts/{account_id}/vectorize/indexes` | Blocked (403) | `vectorize.read` |
| Workflows | `GET /accounts/{account_id}/workflows` | Blocked (401) | `workers-scripts.read` |

**Important:** These results do not prove that any resource class is empty. They prove only that this connected API session could not enumerate it.

### Reauthorization checklist

Reconnect the Cloudflare integration and grant these read scopes:

- [ ] `workers-scripts.read` — Workers Scripts Read
- [ ] `d1.read` — D1 Read
- [ ] `workers-r2.read` — Workers R2 Storage Read
- [ ] `workers-kv-storage.read` — Workers KV Storage Read
- [ ] `page.read` — Pages Read
- [ ] `queues.read` — Queues Read
- [ ] `vectorize.read` — Vectorize Read

Use read scopes for inventory. Do not grant write/admin scopes merely to discover resources. After reconnecting, repeat each GET and record actual IDs, names, bindings, environments, dependencies, and pagination totals. Never retrieve or publish secret values.

## 3. Known STREAMIOV architecture mapping

These are project decisions, not claims that the corresponding Cloudflare resources have been verified in the account.

| Layer | Intended responsibility | Boundary |
|---|---|---|
| Cloudflare Pages | Public homepage, information and downloads at `https://streamiov.pages.dev/` | Not the browser Studio |
| Cloudflare Workers | Server-side Core/API and AI service endpoints where existing resources fit | Inspect existing scripts and bindings before creating anything |
| D1 | Shared relational application data where the existing schema and service design require it | Inspect databases and migrations before changing schema |
| KV / R2 | Existing cache/configuration or object/media storage only where the current implementation uses them | Verify actual bindings and retention/security settings |
| Durable Objects / Queues / Workflows | Coordination, asynchronous jobs, and durable workflow execution if already used by STREAMIOV | Do not create duplicates without dependency evidence |
| Vectorize / Workers AI | AI retrieval and model execution where current code and bindings prove the dependency | Record model/binding metadata only; do not expose credentials |
| Local Studio | Electron app owns camera, microphone, capture, and local audio devices | Device operations remain local |
| External live platform | TikTok LIVE only for the initial product scope | Do not add Twitch, YouTube, Kick, or Facebook adapters |

## 4. Known project references requiring verification

Prior project context identifies the following names/configuration. They are **leads for verification**, not a completed live-account inventory:

- Worker name: `streamiov-core-api`
- D1 name: `streamiov-core-db`
- Worker secret binding name: `STREAMIOV_API_TOKEN` (presence only; never inspect value)
- Workers AI binding name: `AI`
- Compatibility date previously recorded: `2026-10-20`
- Homepage Worker name previously recorded: `streamiov-homepage`
- Homepage source/config reference: `dist/streamiov-homepage-worker/wrangler.jsonc`

After read access is restored, verify each item against the account and repository. Do not assume that a local Wrangler configuration proves a deployed resource exists or is current.

## 5. Safe next steps

1. Reauthorize the least-privilege read scopes in section 2.
2. Enumerate every page of each resource endpoint; retain response evidence and timestamps.
3. Inspect Worker metadata and binding names without reading secret values or secret contents.
4. Inspect Pages projects, deployments, and custom domains; inspect zones/DNS only after the relevant zone IDs are discoverable.
5. Compare deployed resources with tracked Wrangler/config files and application references.
6. Record each resource's ID, type, environment, purpose, dependencies, owner/status, and evidence.
7. Open bounded follow-up issues for concrete gaps; implement changes in isolated branches with tests and rollback notes.

## 6. Change-control and recovery gates

- Preserve all existing resources and data during discovery.
- No deletion, destructive migration, production deployment, DNS cutover, credential rotation, billing change, or TikTok OAuth/security change is part of this inventory.
- Before any later production change, document the exact target, impact, backup/restore method, rollback plan, verification, and maintenance window.
- For D1, establish the database's actual backup/PITR eligibility and recovery procedure from current Cloudflare documentation and the database's settings before relying on it. Do not assume that a backup exists or that restore is risk-free.
- Separate local/development, preview/staging, and production resources explicitly. Do not infer environment from a resource name alone.
- A successful API response, build, or unit test is evidence only for the operation it actually verifies.

## 7. Current completion state

- [x] Connected account identity recognized.
- [x] Account list read successfully.
- [x] Resource endpoints and missing read scopes identified.
- [x] Baseline inventory and architecture mapping documented.
- [ ] Read scopes reauthorized.
- [ ] Complete resource inventory and pagination evidence collected.
- [ ] Bindings, dependencies, deployments, domains, and environment mapping verified.
- [ ] Backup/restore and operational runbooks validated against actual resources.
- [ ] Concrete integration gaps implemented and tested through separate reviewed changes.
