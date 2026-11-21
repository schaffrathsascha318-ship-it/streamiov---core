# D1 Backup & Recovery (Issue #189)

This directory contains an isolated Cloudflare Workflow implementation. It is intentionally not attached to a production Worker and has no real bucket/database identifiers until the read-only account inventory confirms them.

## Configuration

1. Inventory existing Cloudflare resources first. Do not deploy this placeholder config as-is.
2. Replace the R2 bucket placeholder with an already-existing suitable bucket, or obtain explicit owner direction before provisioning anything.
3. Set `CLOUDFLARE_ACCOUNT_ID`, `D1_DATABASE_ID`, and `D1_REST_API_TOKEN` as Worker vars/secret. The token must be least-privilege and remain a Cloudflare secret.
4. Deploy the Workflow only after validating Cloudflare Workflow schedule semantics and the actual account resource configuration.

The daily trigger is UTC midnight. The schedule creates one workflow instance per UTC date; duplicate deliveries are treated as idempotent.

## Export behaviour

- Uses D1 REST API `POST .../export` with `output_format: polling` and D1-compatible dump format.
- Captures and preserves `at_bookmark`, polls until a signed download URL is returned, and never logs the signed URL or token.
- Uploads SQL to R2 with database/bookmark/checksum metadata, reads it back, verifies size and SHA-256, then writes a JSON manifest.
- Fails closed on HTTP/API errors, missing bookmark, export errors, timeout, empty/oversized dumps, missing R2 object, or checksum mismatch.
- No automatic retention deletion is implemented: deletion policy must be designed after inventory and must use explicit safety guards.

## Current safety boundary

This is a first implementation slice, not a production-ready recovery claim. The current worker buffers the SQL dump in memory for WebCrypto SHA-256 and therefore enforces a 256 MiB default size cap. Large production databases require a streaming incremental SHA-256 implementation before enabling this workflow. A restore/import executor and independent D1 test-database validation are also not implemented yet. No production restore is implemented or triggered.

## Verification

Run:

```sh
node --test tests/test_d1_backup_manager.mjs
```

These are mocked contract tests only; they do not prove Cloudflare account access, an actual R2 write, or restore capability.

Official references:
- https://developers.cloudflare.com/api/resources/d1/subresources/database/methods/export/
- https://developers.cloudflare.com/d1/reference/time-travel/
- https://developers.cloudflare.com/workflows/examples/backup-d1/
