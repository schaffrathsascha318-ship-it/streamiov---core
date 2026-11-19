# Streamiov — TikTok App Review Preparation Package

**Status date:** 2026-11-19  
**Existing TikTok app:** Streamiov (Sandbox)  
**Known App ID:** 7694133030948177927  
**Known requested scope:** `user.info.basic`  
**Package status:** Preparation draft. This document is not proof of Developer Console approval, successful live authorization, API entitlement, or submission.

## 1. Purpose and product boundary

Streamiov Studio is a desktop Electron creator studio. It provides Streamiov-owned scene/regie, local media/device controls, audio tools and creator workflows. TikTok is an optional external account connection. TikTok Login Kit is intended to authenticate the creator and, with the `user.info.basic` permission granted, identify the connected TikTok account in the Studio.

Do not describe Streamiov as a TikTok product, imply endorsement, or claim that TikTok controls Streamiov-owned Studio features.

## 2. Exact scope-to-feature mapping

| TikTok product / scope | Intended user-visible feature | Evidence required before claiming it works | Current status |
|---|---|---|---|
| Login Kit / `user.info.basic` | Creator chooses “Mit TikTok verbinden”; after consent, Streamiov identifies the connected account and shows basic profile information and connection state. | Real authorization through the existing app's Sandbox configuration; callback/state/PKCE validation; successful official Display API profile request; disconnect behavior; recording of the complete flow. | OAuth module exists on main. Desktop PKCE correction is in Draft PR #179. Display API profile adapter and Studio harness are in Draft PR #180. No real Sandbox E2E proof recorded. |
| TikTok LIVE chat/gift/like/follow/viewer events | No claim in this submission. | Separate official TikTok product/partner entitlement, documented event schemas and written access confirmation, followed by authorized E2E test. | Not verified / do not claim. |
| TikTok LIVE broadcast start or stream destination | No claim in this submission. | Official product/account entitlement and provider documentation for this exact app/creator, followed by authorized E2E test. | Not verified / do not claim. |
| TikTok native gift-gallery placement | No claim in this submission. | Written TikTok product/partnership approval and commercial/technical terms. | No public API/scope found in current audit; not implemented. |
| Content Posting API / video publishing | Not requested in this submission. | Separate implemented user flow, required scope, review and audit. | Not requested / not part of current claim. |

A unit test with mocked provider responses is not a real TikTok authorization or provider-side approval.

## 3. Review submission text — Login Kit only

Use this text only after the described login and profile flow has been implemented and passed a real authorized Sandbox end-to-end test. If that test has not passed, do not submit this as an already working integration.

> Streamiov is a free desktop streaming studio for creators. We request TikTok Login Kit access with the `user.info.basic` scope so a creator can voluntarily connect their TikTok account to Streamiov Studio. After the creator authorizes the connection, Streamiov uses the basic profile information returned by TikTok to identify the connected account and display its account name, profile image (when provided), and connection status in the Studio. This makes it clear to the creator which TikTok account is connected before using TikTok-related workflows.
>
> Streamiov's scene management, local audio and media controls, and other creator tools are Streamiov-owned features. We use only the official TikTok Login Kit and Display API functionality and only the permission granted by the user. We do not claim TikTok LIVE chat, gift, viewer-event, broadcast-start, or native gift-gallery access through this scope. Any additional TikTok product or permission will be requested separately only after its implementation and eligibility are confirmed.

### Scope justification

- **Why needed:** identify the TikTok account the creator explicitly connected.
- **Where shown:** Studio → Regie / Plattformverbindung → TikTok account connection status and basic profile card.
- **User action:** creator clicks connect, reviews TikTok's consent screen, authorizes, returns to Streamiov and can disconnect.
- **Data minimization:** request only `user.info.basic`; do not request extra profile/video scopes without a separate product need and review.
- **Token handling:** production client secrets and durable token storage must remain server-side in authenticated Streamiov Core. No production client secret may be bundled into the Electron application.

## 4. Demo video recording plan

TikTok's review video must show the actual app UI and real user interaction. Record the actual running Streamiov Studio and the existing TikTok Developer Sandbox flow. Do not create a mock UI, synthetic account response, fake LIVE session, fake gift event, or edited overlay that implies an unimplemented provider feature.

Recommended single end-to-end recording:

1. Show the Streamiov Studio application name and the creator-facing purpose.
2. Open the TikTok connection area in the actual Studio.
3. Click the real “Mit TikTok verbinden” action.
4. Show the official TikTok Sandbox authorization page and the app identity/consent requested.
5. Complete authorization using an authorized Sandbox test account. Do not expose passwords, one-time codes, tokens, client secrets, private email, or unrelated personal data.
6. Return to Studio and show the actual connected state.
7. If the Display API profile flow has passed a real provider test, click “TikTok-Profil laden” and show the real profile data returned by TikTok. If it has not passed, omit this step and do not represent mocked data as provider data.
8. Show the disconnect action and resulting disconnected state if this behavior is included in the approved flow.
9. Briefly show one or two real Streamiov-owned Studio features (for example scene preview/program and audio controls), clearly labelling them as Streamiov features rather than TikTok API products.
10. End with a clear statement that this review request covers Login Kit and `user.info.basic` only.

Recording requirements:
- Capture the real desktop application, readable UI and actual clicks.
- Use a dedicated test account and non-sensitive test data.
- No secrets, access/refresh tokens, authorization codes, personal account details, browser password manager or private notifications in frame.
- Do not cut away errors or failed states in a way that misrepresents the flow.
- Export a supported video format and verify the final file is no larger than TikTok's 50 MB per-video limit (per the current review checklist used by this project).
- Keep an unedited evidence copy for internal audit; create a compressed review copy only after confirming it preserves legibility and truthful sequence.

**Recording owner action required:** the actual machine running Streamiov and an authorized TikTok Sandbox user must perform the live authorization and screen recording. A remote repository check cannot create that genuine user session or capture the user's desktop.

## 5. Public website and legal-link checklist

The repository homepage source at `dist/streamiov-homepage-worker/public/index.html` currently links to:
- `/impressum/`
- `/datenschutz/`
- `/nutzungsbedingungen/`
- `/compliance/`

The corresponding source pages exist in the repository under `dist/streamiov-homepage-worker/public/`. This repository inspection does **not** prove that the current Cloudflare Pages deployment serves those paths successfully, nor that the legal text is complete for the actual data flows.

Before submission, manually verify in a clean browser session:
- `https://streamiov.pages.dev/` loads without an account.
- `https://streamiov.pages.dev/datenschutz/` loads and clearly explains the actual TikTok Login Kit data, purposes, retention, deletion/disconnection, controller contact and relevant third-party processing.
- `https://streamiov.pages.dev/nutzungsbedingungen/` loads and covers the actual Studio and external-platform use.
- `https://streamiov.pages.dev/impressum/` loads and contains complete, current operator details.
- Footer links work on desktop and mobile widths.
- No placeholder text, broken links or contradictory product claims remain.

The existing privacy page is generic in parts and refers users to the imprint for the controller. It must be checked against the actual deployed data flow and, where needed, reviewed by the responsible operator/legal adviser. Do not claim legal compliance solely because a page exists.

## 6. Existing implementation and CI evidence

The following open PRs were inspected on 2026-11-19:

- **PR #178** — official TikTok capability audit. Draft, documentation-only. It records that the public scopes/webhook catalogue reviewed does not document ordinary LIVE gift/chat/viewer-event access and that LIVE/gift entitlements require separate provider confirmation.
- **PR #179** — desktop Login Kit PKCE challenge encoding. Draft. Its dedicated TikTok sandbox OAuth test workflow passed on the inspected head. Full repository verification and Phase 1 agent tests failed on a separate autonomous-runner policy test because the workflow source did not contain the expected `gh pr checks` guard. Do not weaken that test or bypass required checks.
- **PR #180** — Display API basic-profile adapter and Studio sandbox harness. Draft. Its TikTok sandbox OAuth tests and Studio build passed on the inspected head; full repository verification and Phase 1 agent tests failed on the same autonomous-runner policy test. The PR itself states that the Electron flow is sandbox-only and production token brokerage must move to authenticated Core.

All three PRs remain unmerged. Their branches are not the same as the current `main` branch. Therefore their features must not be described as already present in the distributed production Studio.

## 7. Submission readiness gates

Do not mark ready until each applicable item has evidence:

- [ ] Existing Developer app identity and current Production status read from the authorized Developer Console.
- [ ] Exact Login Kit product and `user.info.basic` scope state verified in the Console.
- [ ] Redirect URI in the Console exactly matches the app's actual callback configuration.
- [ ] Desktop PKCE behavior matches the official Desktop Login Kit specification and passes the provider-backed Sandbox flow.
- [ ] Real Sandbox authorization completed successfully with a test account.
- [ ] Real Display API profile request succeeds with the granted scope, or the profile claim is removed from the submission.
- [ ] Disconnect/revocation behavior tested and accurately described.
- [ ] Production token exchange/refresh/storage architecture remains server-side; no production secret in the desktop package.
- [ ] Homepage, Privacy Policy, Terms and Imprint verified live and consistent with actual data processing.
- [ ] Actual end-to-end demo recorded and reviewed for truthfulness and secret/PII exposure.
- [ ] Video file is readable and within TikTok's file-size limit.
- [ ] App description, icon, website, redirect URI, products and scope rationale match the real app.
- [ ] Review text is limited to the product and scope actually implemented.
- [ ] Final app revision and submission status recorded from the Developer Console.

## 8. Explicitly out of scope for this review request

Do not request or claim TikTok LIVE chat, gift, like, follow, share, viewer-presence or LIVE lifecycle events; LIVE start/stream-key provisioning; native TikTok gift-gallery insertion; or zero-fee gift economics unless TikTok provides written product/partner authorization and a documented test path. Streamiov-native gifts may be demonstrated only as Streamiov-owned local catalogue/effects, not as TikTok-native gifts.

## 9. Official TikTok references

- App Review FAQ: https://developers.tiktok.com/doc/getting-started-faq/
- App Review Guidelines: https://developers.tiktok.com/docs/en/app-review-guidelines
- Scopes overview: https://developers.tiktok.com/docs/en/scopes-overview
- TikTok API scopes: https://developers.tiktok.com/docs/en/tiktok-api-scopes
- Display API getting started: https://developers.tiktok.com/docs/en/display-api-get-started
- User info endpoint: https://developers.tiktok.com/docs/en/tiktok-api-v2-get-user-info
- Login Kit: https://developers.tiktok.com/docs/en/login-kit-overview
- Developer Support: https://developers.tiktok.com/support/

## 10. Evidence log

| Date | Check | Result |
|---|---|---|
| 2026-11-19 | Repository homepage footer inspected | Legal and compliance routes are linked in source. Live deployment not independently verified. |
| 2026-11-19 | Legal page source files inspected | Privacy, terms, imprint and compliance source files exist. Legal adequacy/live reachability remain unverified. |
| 2026-11-19 | PR #179 dedicated TikTok OAuth workflow | Passed on inspected head; full repo and Phase 1 checks failed due separate autonomous-runner policy assertion. |
| 2026-11-19 | PR #180 TikTok OAuth workflow and Studio build | Passed on inspected head; full repo and Phase 1 checks failed due separate autonomous-runner policy assertion. |
| 2026-11-19 | Real TikTok Sandbox authorization | Not performed / no evidence available in repository inspection. |
| 2026-11-19 | Real desktop screen recording | Not recorded / must be performed on the actual device. |

**Final rule:** A checked box requires a saved artifact, reproducible test output, verified live URL or Developer Console evidence. No planned, mocked, or unverified feature may be marked complete.
