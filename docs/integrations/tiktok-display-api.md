# TikTok Display API — basic profile

`TikTokDisplayApi` is a server-side consumer of the existing `TikTokOAuth` service. It requests only the three `user.info.basic` fields needed to show the connected creator identity: `open_id`, `display_name` and `avatar_url`.

- Endpoint: `GET https://open.tiktokapis.com/v2/user/info/`
- Fields: `open_id,display_name,avatar_url`
- The OAuth service remains responsible for encrypted token storage, refresh and revocation.
- The Display API adapter returns a token-free profile object and never returns raw OAuth tokens.
- It refreshes an expiring access token before calling TikTok and refuses to call the endpoint if the account or required scope is missing.
- The current Electron usage is a sandbox-only review harness. It retrieves the profile in the trusted main process and exposes only the sanitized profile object to the renderer.
- This does not make the desktop app a production token broker. Production authorization-code exchange, refresh/revocation and durable token storage must move to an authenticated Core service; never embed a production client secret in the desktop app.

TikTok requires approval for the Login Kit and TikTok API products and the user must grant the requested scope. A working local unit test does not establish Console approval or a live sandbox connection.

Official references:
- https://developers.tiktok.com/docs/en/display-api-get-started
- https://developers.tiktok.com/docs/en/tiktok-api-v2-get-user-info

Run:
`node --test tests/tiktok-display-api.test.js`
