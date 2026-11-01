# TikTok OAuth for STREAMIOV

## Existing app only
Use the existing TikTok Developer app Streamiov (App ID 7694133030948177927). Do not create another app. The App ID is not assumed to equal the OAuth client_key; copy the Client key shown in the existing app's Login Kit credentials.

## Sandbox setup
Set these values only in the sandbox server's secret manager:
- STREAMIOV_TIKTOK_SANDBOX_CLIENT_KEY
- STREAMIOV_TIKTOK_SANDBOX_CLIENT_SECRET
- STREAMIOV_TIKTOK_SANDBOX_REDIRECT_URI (must exactly match the registered URI)
- STREAMIOV_TIKTOK_SANDBOX_TOKEN_ENCRYPTION_KEY (base64-encoded 32 random bytes)
- Optional STREAMIOV_TIKTOK_SANDBOX_TOKEN_FILE

Generate an encryption key with: openssl rand -base64 32. Never commit keys, client secrets, access tokens, or refresh tokens.

Production must use a separate deployment and STREAMIOV_TIKTOK_PRODUCTION_* variables, a separate encryption key, separate token file and HTTPS redirect URI. Never reuse sandbox credentials or tokens in production.

## TikTok Console checklist
1. Open the existing Streamiov app and verify App ID 7694133030948177927.
2. In Login Kit credentials, copy the OAuth Client key. Do not derive it from the App ID.
3. Revoke the previously exposed Client Secret and generate a replacement.
4. Register the exact sandbox redirect URI. Scheme, hostname, port, path and trailing slash must match exactly.
5. Confirm Login Kit and user.info.basic are enabled for this app.
6. Keep production credentials separate and inactive until sandbox end-to-end tests pass.
7. Request other products/scopes only through TikTok's approval process. LIVE chat, gifts, viewer events, payouts and Shop finance are not claimed as available.

## Server route integration
Instantiate TikTokOAuth in the server process with environment sandbox for sandbox routes. Use createAuthorizationUrl() behind an authenticated and CSRF-protected connect action, then redirect to the returned URL. Pass only the callback query's code, state and provider error to callback(); never accept a redirect URI from the request. Expose status() only behind the authenticated account route. Use refresh() server-side before expiry. Call disconnect() from an authenticated disconnect action.

The service keeps short-lived PKCE state in memory, exchanges codes server-side, encrypts tokens with AES-256-GCM and environment-bound authenticated data, and writes token files with restrictive permissions. Before horizontally scaling, move pending state into a shared TTL store and tokens into a durable encrypted secret store. The hosting application must also enforce session, CSRF and origin checks around those route handlers.

## Tests
Run: node --test tests/tiktok-oauth.test.js
Tests use fake provider responses and temporary local files. They do not call TikTok and require no live credentials. A real sandbox end-to-end authorization still requires the Console settings and a sandbox test user.

## Permission matrix
config/platforms/tiktok/oauth.json separately records requested, enabled, approved and verified states. Initially only user.info.basic is requested. Other products/scopes remain unrequested and unverified until visibly enabled and approved by TikTok.

## Desktop sandbox boundary (important)
The current Electron bridge is a sandbox integration harness only. Do not distribute a production TikTok client secret inside the desktop app or require end users to configure one locally. Before production, move authorization-code exchange, client-secret use, token refresh/revocation and durable token storage into the authenticated STREAMIOV Core service. The desktop app must receive only a short-lived, scoped connection result/session from Core. Production remains disabled until that server-side design and a real TikTok sandbox end-to-end test are complete.
