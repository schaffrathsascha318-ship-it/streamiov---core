# STREAMIOV Chromebook device control plane — API contract

Status: **design baseline only; not deployed and not connected to a Cloudflare resource**  
Related: [Issue #94](https://github.com/schaffrathsascha318-ship-it/streamiov---core/issues/94), [Issue #91](https://github.com/schaffrathsascha318-ship-it/streamiov---core/issues/91), [PR #95](https://github.com/schaffrathsascha318-ship-it/streamiov---core/pull/95)

## 1. Purpose and boundaries

Provide the missing server side for the outbound-only Chromebook executor in PR #95. The local device polls over HTTPS; no inbound listener, SSH service, browser terminal, arbitrary command endpoint, or remote shell is introduced.

The first release is a small, separately deployed Cloudflare Worker backed by a dedicated D1 database. It is not an extension of the public Pages homepage and must not be mixed into the existing Workers AI gateway. The AI gateway token is not a device credential, enrollment credential, or job-signing key.

This document does not assert that any Cloudflare resource, D1 binding, secret, route, or deployment currently exists. The inventory in `RESOURCE_INVENTORY.md` is still the prerequisite for selecting or creating production resources.

## 2. Version-one scope

Only these executor profiles are permitted, matching PR #95 exactly:

- `diagnostics`
- `git-status`
- `python-tests`

The server stores and signs a profile name, not a command. The job schema requires `args: {}`. Unknown profiles, extra fields, non-empty args, arbitrary paths, shell fragments, environment overrides, and executable names are rejected.

No build, packaging, file-write, install, deployment, release, OAuth, payment, or production profile is part of v1.

## 3. Proposed service and storage

- New Worker name proposal: `streamiov-device-control` (name is provisional until the Cloudflare inventory is complete).
- Dedicated D1 database proposal: `streamiov-device-control-db` (must not reuse or migrate `streamiov-core-db` without a separately reviewed migration).
- No Queue, Workflow, Cron, Durable Object, or Vectorize dependency is required for the first low-volume polling implementation. D1 is the durable source of truth; add Queues/Workflows only after measured need and an explicit design.
- Separate staging and production Worker/database/secret sets. Never point a test client at production.
- No Pages route or public homepage change.

A D1 claim must be serialized and atomic. Use a single conditional `UPDATE ... RETURNING` or a transaction that proves the row was queued, is assigned to the authenticated device, and has not already been claimed. Do not implement claim as an unguarded SELECT followed by UPDATE.

## 4. API routes

All routes require HTTPS and JSON with a strict content-type and body-size limit. Do not enable browser CORS; this is a device/service API, not a browser API. Return generic authentication failures and never echo credentials.

### Device enrollment and lifecycle (admin only)

- `POST /v1/admin/devices/enroll`
  - Requires the dedicated `STREAMIOV_DEVICE_ADMIN_TOKEN`.
  - Creates one device with a server-generated opaque ID, random high-entropy bearer token, and independent random HMAC signing key.
  - Returns the device ID, control-plane origin, bearer token, and signing key exactly once. The operator provisions these locally through a protected file with mode 0600. Never return them again or write them to logs, issues, CI output, or D1 plaintext.
  - Store only a SHA-256 hash of the bearer token. Encrypt the per-device HMAC key at rest with AES-GCM using a separate `STREAMIOV_DEVICE_KEY_ENCRYPTION_KEY` Worker secret. Use a unique random IV per encryption.
- `POST /v1/admin/devices/{device_id}/pause`
- `POST /v1/admin/devices/{device_id}/resume`
- `POST /v1/admin/devices/{device_id}/revoke`
  - Revocation is terminal. Reject future claim and completion requests after revocation; do not silently re-enroll or rotate credentials.
- `GET /v1/admin/devices`
  - Returns metadata only: ID, label, created/last-seen timestamps, status, and software version. Never return hashes, encrypted keys, or secrets.

Admin authentication is separate from device authentication. Do not reuse the AI Worker token or GitHub token. Admin token values belong only in Cloudflare secret storage and the authorized operator's secret manager.

### Job submission (admin/service only)

- `POST /v1/admin/jobs`
  - Requires the dedicated admin/service credential.
  - Accepts only `device_id`, one fixed `profile`, an idempotency key, and a short human-readable reason.
  - Server generates the job ID, timestamps, nonce, empty args object, and signature. The caller cannot provide a command, arguments, path, executable, expiry, signature, or shell string.
  - Reject paused/revoked/unknown devices and duplicate idempotency keys.
- `GET /v1/admin/jobs/{job_id}`
  - Returns lifecycle metadata and bounded result summary; access is admin-only.

### Device polling and completion

- `POST /v1/devices/{device_id}/jobs/claim`
  - Authenticates the bearer token against the stored hash and checks device status.
  - Device ID in the URL must match the authenticated device.
  - Returns `{"status":"idle"}` when no eligible work exists.
  - Otherwise atomically claims exactly one queued job, creates a lease, updates last-seen, and returns the exact HMAC envelope expected by PR #95: `{"job":{"id":"…","device_id":"…","profile":"…","issued_at":0,"expires_at":0,"nonce":"…","args":{}},"signature":"<hex>"}`.
  - Use canonical JSON identical to the local client's `json.dumps(sort_keys=True, separators=(",", ":"), ensure_ascii=False)` UTF-8 encoding before HMAC-SHA256.
  - Job validity is at most 300 seconds. The claim lease must be longer than the maximum local execution timeout plus completion margin (initial proposal: 20 minutes), and must be server-generated.
- `POST /v1/devices/{device_id}/jobs/{job_id}/complete`
  - Authenticates the same device and requires the job to be claimed by it and still within the completion policy.
  - Validates an exact schema, bounded output (at most 16 KiB), fixed profile, valid status, integer exit code/timestamps/duration, and 64-character SHA-256 digest.
  - Recompute the output digest server-side. Treat identical repeated completion as idempotent success; reject conflicting second completions.
  - Persist completion metadata and redacted output. Never store bearer tokens, signing keys, authorization headers, or environment dumps.

The current local client posts `device_id` in the claim body and posts a result object on completion. The implementation must keep those wire shapes compatible or update the client and contract together with tests.

## 5. State machine and replay policy

Device states: `active`, `paused`, `revoked`.

Job states: `queued` → `claimed` → `succeeded` or `failed`.

A claim lease that expires without a completion becomes `uncertain`, **not automatically queued again**. PR #95 intentionally records job IDs locally and refuses duplicate or previously interrupted work. Automatically reissuing the same job would conflict with that replay protection; automatically creating a new job could duplicate effects. Recovery therefore requires an operator to inspect the local audit and server record, then explicitly submit a new job with a new ID if safe.

Completion must be idempotent. Claim must be atomic. Duplicate admin submissions with the same idempotency key must return the original job rather than create a second one.

## 6. D1 schema baseline

Use migrations and foreign keys. Proposed logical tables:

- `devices`: `id` primary key, `label`, `status`, `token_hash`, `encrypted_signing_key`, `key_iv`, `created_at`, `last_seen_at`, `revoked_at`.
- `jobs`: `id` primary key, `device_id` foreign key, `profile`, `status`, `idempotency_key`, `reason`, `issued_at`, `expires_at`, `nonce`, `lease_expires_at`, `claimed_at`, `completed_at`, `exit_code`, `duration_seconds`, `result_sha256`, `output`.
- Unique index on `(device_id, idempotency_key)`; indexes on `(device_id, status, issued_at)` and `(status, lease_expires_at)`.

Never store plaintext device bearer tokens or plaintext HMAC keys. Keep D1 data minimal and set a documented retention/cleanup policy for bounded outputs and audit metadata. Do not delete uncertain records as a way to make retries work.

## 7. Security requirements

- Use constant-time comparison for bearer-token hash verification and HMAC verification where applicable.
- Generate tokens, keys, nonces, IDs, and IVs with Web Crypto cryptographically secure randomness.
- Separate secrets by purpose: admin token, key-encryption key, and per-device bearer/signing credentials. Never reuse the AI gateway secret.
- Per-device credentials are unique; revoke immediately on compromise. No credentials in logs or model context.
- Strict schema validation, request size limits, bounded output, rate limits, generic auth errors, and security event audit.
- Never allow client-supplied commands or server-side command execution. The Worker only queues, signs, leases, and records jobs.
- No cross-device job claims. No job for paused/revoked devices.
- No auto-merge, production deployment, arbitrary Git operations, or changes to TikTok OAuth/security.
- Staging tests use synthetic credentials and an isolated D1 database.
- Keep secrets out of Wrangler config, migrations, source, GitHub issues, PR bodies, and Actions logs.

## 8. Required tests before deployment

1. Enrollment returns a secret once; D1 contains only token hash and encrypted signing key.
2. Invalid/missing admin token cannot enroll, enqueue, pause, resume, revoke, or read admin data.
3. Invalid/revoked/paused device credentials cannot claim or complete.
4. Device A cannot claim or complete Device B's job.
5. Atomic concurrent claim allows exactly one claimant.
6. Job signature matches the Python client's canonical JSON/HMAC implementation byte-for-byte.
7. Expired, malformed, extra-field, unknown-profile, non-empty-args, and oversized jobs are rejected.
8. Duplicate idempotency key does not create a second job.
9. Repeated identical completion is idempotent; conflicting completion is rejected.
10. Expired claim becomes uncertain and is never automatically requeued.
11. Output digest is recomputed and validated; output is bounded and redacted.
12. No secret values appear in responses, logs, test output, or D1 plaintext.
13. Pause/resume/revoke take effect immediately on the next device request.
14. Local executor contract tests pass against a local mock and then an isolated staging Worker/D1 deployment.

## 9. Delivery sequence and gates

1. Complete the Cloudflare read-only resource inventory and confirm available environments, D1 databases, Workers, bindings, and existing routes. The current connector permission gap is documented in Issue #107/PR #108.
2. Confirm whether an appropriate non-production D1/Worker already exists. Reuse only after identity, environment, schema, ownership, and dependency checks; otherwise propose a new isolated staging resource.
3. Implement the Worker and D1 migration on an isolated feature branch. Add unit/integration tests and local Wrangler tests; do not deploy.
4. Review the D1 migration, secret provisioning procedure, recovery model, and rollback plan.
5. Obtain a specific production resource/deployment approval only if a production resource or route must be created or changed. User's general project authorization does not bypass this gate.
6. Deploy to isolated staging only after its resource and secret configuration are verified; run the full contract suite.
7. Update PR #95 client tests against the staging API and document local Chromebook one-shot acceptance. Do not install or enable the service automatically.
8. Only after explicit human acceptance, enroll the actual Chromebook and run one harmless `diagnostics` job. Do not start `--loop` by default.

## 10. Current blockers

- Cloudflare connector cannot yet enumerate account resources because read scopes are missing. Do not assume a D1/Worker is absent or create duplicates.
- The control-plane Worker and dedicated D1 database are not verified to exist.
- No admin/enrollment secrets have been provisioned.
- No server API has been deployed.
- No actual Chromebook command has been run.
- PR #95 remains a draft and is not remotely operable yet.
