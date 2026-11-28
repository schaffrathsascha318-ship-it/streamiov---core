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


## Official TikTok documentation review — 2026-11-19

This section records a fresh review of the public TikTok for Developers documentation. It is separate from repository tests and does not imply access to the private Developer Console for the existing Streamiov app.

### Publicly documented products and scopes

The current public Scopes Reference lists Login/User Info scopes (`user.info.basic`, `user.info.profile`, `user.info.stats`), video scopes (`video.list`, `video.manage`, `video.publish`, `video.upload`), and other products such as Share Kit, Content Posting API, Display API, Research API and Data Portability API. It does not list a public TikTok LIVE chat, LIVE gift, LIVE like, LIVE follow, viewer-presence, LIVE-room-control or stream-key scope.

Sources:
- https://developers.tiktok.com/docs/en/tiktok-api-scopes
- https://developers.tiktok.com/docs/en/scopes-overview

**Conclusion:** The current public Developer API scope catalogue does not provide evidence that ordinary Login Kit approval grants LIVE chat/gift/event access. These capabilities must remain NOT AVAILABLE THROUGH THE PUBLICLY DOCUMENTED SCOPES / PROVIDER CONFIRMATION REQUIRED unless TikTok supplies a separate official product, partner entitlement or written technical specification for this app.

### Publicly documented webhook events

The current public Webhooks Events page documents:
- `authorization.removed`
- `video.upload.failed`
- `video.publish.completed`
- `portability.download.ready`

It does not document LIVE chat, gift, like, follow, share, viewer join/leave or LIVE lifecycle webhook events. The documented webhook transport is HTTPS POST; TikTok describes best-effort at-least-once delivery, so consumers must be idempotent. That delivery contract does not create event types that TikTok does not document.

Sources:
- https://developers.tiktok.com/docs/en/webhooks-events
- https://developers.tiktok.com/docs/en/webhooks-overview

**Conclusion:** Do not build a purported TikTok LIVE webhook consumer against guessed event names or fabricated payloads. The only safe path for LIVE events is a separate official TikTok product/partner authorization with documented event schemas and explicit permission for this app.

### Login Kit and app review

TikTok's Login Kit documentation confirms that:
- Login Kit authenticates the user; it is not itself a LIVE event API.
- `user.info.basic` is the baseline scope; additional data requires pre-approval.
- The authorization-code exchange, client secret and refresh-token handling belong server-side.
- Desktop Login Kit uses loopback redirect URIs with a port and PKCE.

The App Review Guidelines require a complete public website, visible Privacy Policy and Terms links, a clear explanation of each product/scope, and an end-to-end demo video showing the real integrated UI. An app that is still only in development/testing is not normally eligible for approval.

Sources:
- https://developers.tiktok.com/docs/en/login-kit-overview
- https://developers.tiktok.com/docs/en/app-review-guidelines
- https://developers.tiktok.com/docs/en/getting-started-faq

### Native TikTok gifts vs. STREAMIOV-native gifts

These are separate systems and must stay separate:

1. **TikTok-native gifts:** Gifts purchased/sent inside TikTok remain governed by TikTok's gift catalogue, eligibility, payout and platform terms. Streamiov may only display/process real incoming gift events if TikTok grants an official, documented event interface and access to this app.
2. **STREAMIOV-native gifts:** Original Streamiov gifts/effects belong to Streamiov's own catalogue/runtime and must not be labelled as TikTok coins or represented as purchasable in TikTok unless TikTok explicitly approves that placement.
3. **Official TikTok gift-gallery placement:** No public Developer API or scope found in the current public scope catalogue enables a third-party app to insert custom gifts into TikTok's native gift gallery. This is a commercial/product-partnership request, not an implementation task that can be solved by OAuth code.
4. **0% TikTok share:** A zero TikTok share for gifts sold or surfaced through TikTok cannot be assumed or enforced by Streamiov code. It requires TikTok's written confirmation of the exact commercial model. Do not launch, collect money or promise creator payouts under this arrangement without that confirmation and a separately validated lawful settlement path.

The existing gift issue #60 correctly keeps TikTok-native gifts separate from Streamiov-native gifts. Issue #128's country gate must remain default-deny and must not treat a different TikTok product's country eligibility as approval for LIVE gifts.

### TikTok LIVE output is separate from Login Kit

A successful OAuth login does not create a LIVE room, grant third-party broadcast permission, issue a stream URL/key, or prove an RTMP/RTMPS destination is available. The current repository audit also finds no verified Core-side official LIVE-start integration. Any manual stream-key workflow is a distinct account entitlement controlled by TikTok and must not be inferred from OAuth status. Never scrape private endpoints, reverse-engineer undocumented app traffic, or ask creators to expose reusable stream keys.

### Current evidence-based capability status

| Capability | Public official documentation reviewed | Repository evidence on main | Required next proof |
|---|---|---|---|
| TikTok Login Kit | Documented | OAuth service exists; only `user.info.basic` configured | Verify existing app's actual Console product/scope, then complete real sandbox authorization |
| User profile basics | Documented under `user.info.basic` | Scope requested; no verified live account flow | Real authorized API call and safe Core/Studio state |
| Extended profile/stats | Documented scopes exist; require approval and user consent | Not requested in current module | Verify whether needed; do not request until UI/use case is ready |
| Public video list | `video.list` documented | Not requested | Separate approved scope and real E2E only if required |
| Upload/direct post | `video.upload` / `video.publish` documented | Not requested and outside current LIVE-first acceptance | Separate product review and user consent if later required |
| TikTok LIVE chat/gifts/likes/follows/viewer events | No such scopes/event types in the public docs reviewed | No verified receiver/consumer | Written TikTok product/partner confirmation plus event schema, entitlement and test access |
| Third-party LIVE output / stream-key provisioning | Not established by Login Kit or the reviewed public scope list | Not verified | TikTok account entitlement and official instructions for the exact creator/app |
| Native gift-gallery insertion | No public Developer API/scope found | Not implemented | Written TikTok product/partnership approval and commercial terms |
| Zero TikTok commission on gallery gifts | Not a technical API capability | Not agreed/verified | Written commercial agreement for the exact model |
| TikTok payout/creator settlement | Not established by the reviewed scopes for this use case | Not implemented | TikTok confirmation of settlement model and legal/accounting review |

### Required TikTok clarification request

The next external step is one consolidated, non-binding technical/product inquiry through an authorized TikTok Developer Support or partner contact for the existing app **Streamiov (Sandbox)** (App ID `7694133030948177927`). It must request written answers to these questions:

1. Which official product, program or partner entitlement enables a third-party desktop Studio to receive LIVE chat, gift, like, follow, share, viewer join/leave and LIVE lifecycle events? Provide official docs, event schemas, required app products/scopes, approval path, rate limits, regional availability and sandbox/test access.
2. Is there an official API or approved account entitlement to create/start a TikTok LIVE broadcast or obtain a short-lived RTMP/RTMPS destination for a creator's own account? What are the eligibility rules and supported desktop workflow?
3. Can original third-party Streamiov gifts be submitted for placement in TikTok's native gift gallery? If so, what are the creator/network/agency/product requirements, asset rules, countries, review process and technical submission route?
4. Can such a gallery arrangement operate with **0% TikTok revenue share**, with the streamer receiving the full gift proceeds? If not, what exact contractual fees, payout rules and settlement model apply?
5. Are these capabilities available to the existing app ID, and what exact changes (if any) are required? Do not create a second app or change existing credentials as part of the inquiry.

No external inquiry has been sent by this audit. Sending it requires an authenticated, authorized TikTok Developer/partner channel; do not claim a request was submitted unless the provider confirms receipt. No contract, payment, app resubmission or credential change is authorized by this document.

### Immediate implementation order

1. Preserve the existing app, OAuth configuration, tokens and credentials. Do not rotate or replace anything as part of research.
2. Complete a repository-wide search and finish authenticated Core connect/callback/status/disconnect wiring around the existing OAuth module, with account isolation, CSRF/session checks, server-only secrets and actual permission state.
3. Prepare the sandbox end-to-end test plan and only run it using the existing app/test account after verifying the registered redirect URI and credentials through the authorized Console.
4. Implement the documented non-LIVE APIs only if they serve an agreed Studio function and are actually approved; do not expand scopes speculatively.
5. Send the consolidated provider inquiry through an authorized channel and track each answer separately.
6. Keep LIVE events, third-party LIVE output, native gift-gallery placement and zero-share economics visibly blocked until written provider evidence and a real test entitlement exist.
7. Continue the Streamiov-native gift gallery and local Regie effects independently; they must work without pretending to be TikTok-native gifts.

**Audit rule:** A repository module, mock test, OAuth login, TikTok LIVE access in the creator's own app, a third-party blog, or a successful HTTP response is not proof of a TikTok-approved product entitlement. Only current Developer Console evidence, official TikTok documentation/communication and reproducible authorized end-to-end tests may change the status above.
