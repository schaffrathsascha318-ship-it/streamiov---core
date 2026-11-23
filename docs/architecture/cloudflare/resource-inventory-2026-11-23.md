# Cloudflare resource inventory and architecture

**Snapshot date:** 2026-11-23  
**Evidence status:** partial; account identity is available, resource-list read permissions are not.  
**Change status:** read-only discovery only. No Cloudflare resource, DNS record, secret, binding, deployment, billing setting or database was changed.

## Evidence classes

- **Owner-provided configuration note:** resource name/configuration previously supplied by the Streamiov owner; not independently refreshed against Cloudflare.
- **Repository evidence:** source/configuration exists in this Git repository.
- **Blocked:** the connected Cloudflare API session returned 401/403 for the resource-list GET. The resource may exist; absence must not be inferred.

## Known resource register

| Resource | Known identifier / configuration | Intended responsibility | Environment / status | Evidence |
|---|---|---|---|---|
| Cloudflare Pages homepage | `https://streamiov.pages.dev/`; Pages project name believed to be `streamiov` | Public information, download hub and project entry point only | Public production URL owner-reported; project/deployment inventory blocked | Owner-provided configuration note |
| Homepage Worker/assets | `streamiov-homepage`; config path owner-reported as `dist/streamiov-homepage-worker/wrangler.jsonc`; assets `./public` | Pages/homepage asset delivery and static downloads; not the Studio app or private Core | Deployed state and route association blocked | Owner-provided configuration note |
| Core API Worker | `streamiov-core-api` | Authenticated public gateway to private Streamiov Core; must not expose private database/admin endpoints | Owner-reported online; health response previously included `external-core-api`, `online`, `production_verified:false`; current state blocked | Owner-provided configuration note |
| Core D1 database | `streamiov-core-db` | Existing Core metadata/state database; private access only through authenticated server-side APIs | Existence owner-reported; database ID, schema, migrations, bindings and backups blocked | Owner-provided configuration note |
| Core API secret name | `STREAMIOV_API_TOKEN` | Worker-to-Core authentication token; record name/presence only, never value | Owner-reported; secret metadata/presence not refreshed | Owner-provided configuration note |
| Core AI binding | `AI` | Cloudflare Workers AI binding for permitted server-side AI tasks | Owner-reported; binding/model/quota configuration not refreshed | Owner-provided configuration note |
| Core Worker compatibility date | `2026-10-20` | Worker runtime compatibility | Owner-reported; not refreshed | Owner-provided configuration note |
| AI Worker source | `infrastructure/cloudflare/streamiov-ai-worker/` | Specialist/AI worker service; model noted by owner as `@cf/zai-org/glm-4.7-flash` | Source exists in repository; deployment, bindings, routes, secrets and live health blocked | Repository evidence + owner note |
| Liberty TV Worker source | `infrastructure/cloudflare/streamiov-liberty-tv-worker/` | Separate Liberty TV project worker; not assumed to be Streamiov Core | Source directory exists; account deployment/ownership unknown | Repository evidence |
| Voice signalling Worker | `infrastructure/cloudflare/streamiov-voice-worker/` in PR #238 | Optional WebRTC signalling using one Durable Object per room | Draft source only; not deployed; no production namespace or secrets | Draft PR #238 |
| Voice Durable Object | Class `VoiceRoom`, binding `VOICE_ROOMS` in PR #238 config | Isolated room signalling/ticket state | Source migration only; not provisioned | Draft PR #238 |

## Required inventory — blocked until read scopes are reauthorized

The following categories were not verified. Do not treat them as absent.

| Category | Required read evidence | Current state |
|---|---|---|
| Workers/scripts | Script names, IDs, routes, deployments, settings, compatibility dates, bindings, secret names/presence | Blocked: Workers Scripts metadata/content read scopes |
| Pages | Project IDs, production branch, latest deployments, custom domains, environment variables/bindings | Blocked: Pages read scope |
| D1 | Database IDs, names, region, size, tables, migration history, bindings, export/Time Travel configuration | Blocked: D1 read scope |
| KV | Namespace IDs/names, binding references, key counts/metadata (never secret values) | Blocked: Workers KV Storage read scope |
| Durable Objects | Namespace IDs, class bindings, migrations and environment | Blocked: Durable Objects read scope |
| Queues / Workflows | Queue names, producers/consumers, workflow definitions and bindings | Blocked: Queues/Workflows read scopes |
| Vectorize | Index names, dimensions, metadata, Worker bindings | Blocked: Vectorize read scope |
| AI | AI bindings, model names, usage/quota settings and Worker references | Blocked: Workers AI read metadata |
| DNS / routes / tunnels | Zones, DNS records, Worker routes, tunnel IDs/connectors, origin exposure | Blocked: Zone/DNS and Tunnel read scopes |
| R2 | Existing bucket presence/metadata only if separately authorized | **Permanently excluded from Streamiov architecture and implementation.** No bucket, binding, backup or use may be created or enabled. Current account bucket presence is not asserted. |

### Permission failure observed

Read-only Cloudflare requests for account resource lists were rejected with 401/403. The connection identified the account but did not authorize the required reads. Scopes reported as missing include:

- Workers Scripts metadata/content read
- D1 read
- Pages read
- Workers KV Storage read
- Queues read
- Zone read

Durable Objects, Workflows, Vectorize, Tunnel and AI resource metadata also remain unverified. Reauthorize only read scopes required for the inventory. No write/admin scopes are needed for discovery.

## Canonical target architecture

1. **Public Pages homepage:** static public content, downloads, release notes, checksums, legal pages and project status. No private Core APIs, admin UI, secrets, account/session tokens or device Studio runtime.
2. **Core API Worker / Cloud Gateway:** authenticated, rate-limited edge gateway. It validates client identity, routes permitted requests to the private Core and exposes only minimal health/capability metadata. The Worker is not the persistent Core database or file store.
3. **Private Streamiov Core:** long-running server on an owner-controlled Linux host. The origin must not be directly reachable from the public Internet; use an authenticated outbound tunnel/private connection plus restrictive firewall. A permanent Linux host is a prerequisite. A Chromebook is development-only.
4. **D1:** existing `streamiov-core-db` is retained pending inventory. Use only for the data it already owns; schema, migrations, backup and Time Travel policy must be inspected before changes. D1 Time Travel is supplemental recovery, not an independent off-site backup.
5. **AI Worker:** server-side specialist/AI service, isolated from public homepage assets and local device I/O. AI bindings and quotas must be inventoried before expanding use.
6. **Local Studio (Electron):** camera, microphone, audio devices, scene composition and local production remain on the user's device. It calls authenticated Core APIs; it is not hosted as a Pages browser app.
7. **Voice signalling (proposed):** separate Worker/DO source in PR #238; no deployment until secrets, TURN and two-client acceptance are ready. Media is peer-to-peer; signalling Worker does not receive or record media.
8. **External live platform:** follow the currently approved Streamiov platform scope. Do not add new platform adapters or modify TikTok OAuth/security settings as part of Cloudflare inventory.

## Security, environment and deployment controls

- Separate development and production account resources, D1 databases, Worker variables/secrets and Pages deployments. Do not point local development at production by default.
- Record secret names and whether configured; never record values, print tokens, or include credentials in GitHub issues/docs.
- Public health responses must not disclose private IPs, internal hostnames, D1 IDs, account emails, stack traces or admin routes.
- Core origin should accept only the authenticated gateway/tunnel path; verify direct-origin denial before claiming protection.
- Use least-privilege service tokens and read-only discovery credentials. Keep platform OAuth secrets isolated from Core, AI and Voice signing keys.
- All D1 migrations require schema export, backup, dry-run, rollback plan and explicit review.
- No production deployment, DNS change, secret rotation, billing change, data deletion, R2 use or destructive migration is authorized by this inventory.
- Backups use the filesystem/age adapter first (PR #239); R2 remains excluded. A real Linux host, public-key recipient and separate backup volume are required before the scheduled service can be enabled.
- Voice Worker/DO and optional self-hosted coturn remain source-only until separately configured and verified.

## Next inventory steps

1. Reauthorize the Cloudflare connection with read-only Workers Scripts, D1, Pages, KV, Queues and Zone scopes (plus read access for DO, Workflows, Vectorize, AI and Tunnel metadata if available).
2. Repeat account-scoped GET-only discovery and save resource IDs, environment, bindings, route mappings, migration versions, deployment timestamps and evidence.
3. Compare discovered resources against this register; identify duplicates/orphans without deleting or editing anything.
4. Document the private Core origin/tunnel state and verify whether the permanent Linux host exists. If it does not, mark hosting **BLOCKED**.
5. Build an approved dependency and rollback map before any integration or deployment.

## Related work

- Issue #107 — Cloudflare inventory and architecture.
- Issue #189 — Streamiov Cloud, private Core, no-R2 and backup/recovery boundaries.
- PR #238 — source-only Voice signalling Worker/DO.
- PR #239 — encrypted filesystem backup and safe restore staging, no R2.
