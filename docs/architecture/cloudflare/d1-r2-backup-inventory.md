# Issue #189 – initial repository inventory

Date: 2026-11-22

## Scope and evidence

This is a read-only repository inspection of `main` at commit `98bf1e14271601d4e14d71837f88940962f05211`. It is not a Cloudflare-account inventory and does not prove the production account's resource state.

## Findings

- The repository contains `infrastructure/cloudflare/streamiov-ai-worker/wrangler.jsonc`. It declares only the Workers AI binding `AI`; it does not declare a D1 binding, R2 bucket binding, or Workflow.
- The repository tree contains no Core D1 Wrangler configuration, D1 migration directory, or D1/R2 backup Workflow configuration.
- `core/cloud-backup.js` is a local JSON-file backup helper. It is not a D1 SQL export, an R2 backup, or a verified restore implementation.
- `infrastructure/backup/core/backup-policy.json` explicitly marks production status as `NOT_VERIFIED`.
- The repository README describes Cloudflare automation as read-only checks plus a separate manually owner-approved deployment. No production deployment was attempted.

## Blockers to real-resource verification

1. The GitHub-connected tool session can inspect the repository but has no Cloudflare D1/R2/Workers/Workflows inventory action available.
2. The repository does not identify a D1 database UUID, the account's R2 bucket, or a Core Worker/Workflow binding for this feature.
3. Therefore the actual D1 storage subsystem (production vs alpha), Time Travel retention, existing R2 buckets, migrations, bindings, and secret presence remain **unknown**. No resource was created or modified.

## Safe next implementation step

Before enabling a scheduled export, connect a read-only Cloudflare inventory path or provide the minimum Cloudflare read permissions for D1 databases, D1 migrations/bookmarks, R2 buckets, Workers scripts/bindings, and Workflows. Export execution additionally requires a least-privilege D1 export token stored only as a Cloudflare secret. Do not put credentials in GitHub.

## Safety

No production database, bucket, Worker, secret, migration, or deployment was changed. No backup or restore has been claimed. Production restore remains a separately authorized destructive operation.
