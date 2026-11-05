# TikTok capability audit — repository evidence

Audit baseline: `main` after OAuth refresh-token rotation fix PR #125.

This document records what can be proven from the repository. It does **not** claim that TikTok has approved a product, scope, LIVE API, or production connection.

## Verified in repository

| Area | Repository evidence | Status |
|---|---|---|
| Existing TikTok app reference | `config/platforms/tiktok/oauth.json` names the existing app ID and explicitly says it is not the OAuth client key | RECORDED; console mapping not verified |
| OAuth service | `core/integration/tiktok-oauth.js` implements authorization URL creation, PKCE S256, state validation, code exchange, encrypted environment-bound token storage, refresh, revoke, and status | IMPLEMENTED AS A SERVICE MODULE |
| Requested scope | OAuth module requests only `user.info.basic`; config lists only that scope as allowed | CONFIGURED; actual console enablement/approval not verified |
| Refresh rotation | PR #125 prevents reuse of a previous refresh token after successful rotation and coalesces concurrent refreshes | CI TESTED |
| Automated OAuth tests | `tests/tiktok-oauth.test.js` uses mocked provider responses and temporary files | AUTOMATED MOCK TESTS; not a real TikTok authorization |
| Sandbox/production separation | Separate environment prefixes, token file names, and environment-bound encryption AAD are present | IMPLEMENTED IN MODULE; deployment separation not verified |
| Studio/Core connection | Repository documentation describes the server-side integration boundary, but the reviewed OAuth module itself is not proof of a connected Studio/Core account flow | NOT VERIFIED |
| TikTok LIVE events | No evidence in the reviewed OAuth service/config of an authorized LIVE event subscription, webhook, or event consumer | NOT IMPLEMENTED / NOT VERIFIED |
| TikTok gifts | No evidence in the reviewed OAuth service/config of real gift-event ingestion | NOT IMPLEMENTED / NOT VERIFIED |
| Real LIVE output | README says official platform sign-in is not implemented and the encoder path requires a user-provided RTMP destination | NOT VERIFIED |

## Permission and capability matrix

The labels below deliberately distinguish repository configuration from provider approval.

| Capability | Requested by current OAuth module | Console enabled | Provider approved | Real end-to-end verified | Status |
|---|---:|---|---|---|---|
| Login Kit / `user.info.basic` | Yes | Not verified | Not verified | No | CONFIGURED; BLOCKED pending console and real sandbox verification |
| TikTok LIVE chat events | No | Not verified | Not verified | No | BLOCKED / NOT VERIFIED |
| TikTok LIVE gift events | No | Not verified | Not verified | No | BLOCKED / NOT VERIFIED |
| Viewer events | No | Not verified | Not verified | No | BLOCKED / NOT VERIFIED |
| Creator payout data | No | Not verified | Not verified | No | NOT IN LAUNCH IMPLEMENTATION |
| Shop finance data | No | Not verified | Not verified | No | NOT IN LAUNCH IMPLEMENTATION |
| TikTok stream creation / stream key | No evidence in reviewed OAuth module | Not verified | Not verified | No | NOT VERIFIED; must be assessed separately from Login Kit OAuth |

## Important implementation gap

The presence of `TikTokOAuth` is not equivalent to a complete Studio integration. The module is a reusable OAuth service, while the repository evidence reviewed for this audit does not establish all of the following as complete:

1. Authenticated Core connect/callback/status/disconnect routes wired to this service.
2. A real account authorization against the existing TikTok Sandbox app.
3. A persisted permission record sourced from the provider/console rather than a hard-coded requested scope.
4. A Studio connection UI backed by the real Core account state.
5. An authorized LIVE event subscription/receiver and validated event adapter.
6. A real end-to-end LIVE session on an authorized account.

Do not expose client secrets or provider tokens in the Electron application. The production authorization-code exchange, refresh, revocation, and token storage must remain server-side.

## Next implementation order

1. Keep the current app and OAuth settings unchanged. Verify the existing app's Client Key, redirect URI, Login Kit status, and approved scopes in the TikTok Developer Console without rotating or replacing credentials as part of this audit.
2. Implement and test authenticated Core routes around the existing OAuth service. Keep sandbox and production isolated.
3. Complete a real Sandbox authorization using the existing app and a test account; record only non-secret evidence and actual returned scopes.
4. Build the capability matrix from actual console/API evidence. Do not request new scopes or resubmit the app until a concrete missing permission is verified.
5. Only then implement LIVE event ingestion for capabilities that are officially available and actually authorized.
6. Test event validation, deduplication, reconnects, and real LIVE delivery separately from mocked tests.

## Acceptance status

- OAuth refresh-token rotation regression tests: **CI PASSED** in PR #125.
- OAuth module behavior: **automated mock coverage exists**.
- Real Sandbox authorization: **NOT TESTED**.
- Provider Console scope approval: **NOT VERIFIED**.
- TikTok LIVE chat/gift event access: **BLOCKED / NOT VERIFIED**.
- Real TikTok LIVE broadcast: **NOT TESTED**.

This audit is intentionally conservative. Update a status only when a reproducible test or provider-side evidence supports the change.
