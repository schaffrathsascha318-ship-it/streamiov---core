# STREAMIOV device control Worker

This Worker is the server-side counterpart for the guarded Chromebook executor in PR #95.

## Current state

**Implementation branch only. Not deployed. Not enrolled. Not connected to a production D1 database.**

The Worker is intentionally separate from:
- `streamiov-ai-worker` and its AI token/binding;
- the public Pages homepage/download hub;
- the existing Core API and `streamiov-core-db`.

The Worker config names a dedicated D1 database proposal but deliberately contains no `database_id`. Do not deploy until the read-only inventory in Issue #107 confirms whether an appropriate staging resource already exists and the owner approves any required resource creation.

## Local checks

From this directory, with a compatible Wrangler version installed:

```sh
npx wrangler dev --local
```

Apply migrations only to an explicitly isolated local or staging database:

```sh
npx wrangler d1 migrations apply streamiov-device-control-db --local
```

No production migration or deployment is part of this PR.

## Required secrets

Provision only after a verified staging resource has been selected:

- `STREAMIOV_DEVICE_ADMIN_TOKEN`: independent random bearer token, at least 32 characters.
- `STREAMIOV_DEVICE_KEY_ENCRYPTION_KEY`: 32 cryptographically random bytes encoded as base64url.

Never reuse `STREAMIOV_API_TOKEN`, the AI Worker token, GitHub credentials, TikTok credentials, or any other project secret.

The enrollment endpoint returns a device token and HMAC signing key once. Store them only in a local protected secret file (mode 0600); do not paste them into chat, GitHub, CI logs, or issue comments. If the one-time response is lost, revoke the device and enroll a replacement.

## API

- `GET /health`
- `GET /v1/admin/devices`
- `POST /v1/admin/devices/enroll` with `{"label":"chromebook-dev"}`
- `POST /v1/admin/devices/{id}/pause`
- `POST /v1/admin/devices/{id}/resume`
- `POST /v1/admin/devices/{id}/revoke`
- `POST /v1/admin/jobs` with `device_id`, fixed `profile`, `idempotency_key`, and `reason`
- `GET /v1/admin/jobs/{job_id}`
- `POST /v1/devices/{id}/jobs/claim`
- `POST /v1/devices/{id}/jobs/{job_id}/complete`

The server signs only fixed profile names. It never accepts a command, executable, arbitrary arguments, path, shell string, or environment override. A claim is atomic. Expired queued jobs become `expired`; a claim whose lease expires becomes `uncertain` and is never automatically requeued.

## Release gates

1. Complete Issue #107's read-only Cloudflare inventory.
2. Select or provision an isolated staging Worker and D1 database; never guess resource IDs.
3. Set the two dedicated staging secrets without printing them.
4. Run migration and integration tests against local D1 and isolated staging.
5. Verify the exact wire contract against PR #95.
6. Do not install/start the Chromebook service until a separate human one-shot acceptance step.
7. Production resource creation, route changes, deployment, and credential provisioning require a specific reviewed approval.

No TikTok OAuth/security, homepage, Core API, AI Worker, existing production database, or DNS change is authorized by this implementation.
