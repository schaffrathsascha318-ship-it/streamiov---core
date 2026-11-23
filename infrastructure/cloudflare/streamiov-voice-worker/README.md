# Streamiov Voice Signalling Worker

This worker provides authenticated WebRTC signalling only. Audio/video media is peer-to-peer WebRTC; the worker never receives media tracks and never records calls.

## Authentication contract

The Streamiov Core issues a short-lived HS256 JWT after checking a live account session and persistent room membership. Claims are restricted to:

- `iss=streamiov-core`, `aud=streamiov-voice`
- `sub`: authenticated account ID
- `room`: 32-character room ID
- `role`: owner, moderator, member, or guest
- `iat`, `nbf`, `exp` (maximum token lifetime 300 seconds)
- random `jti`

The Core and this Worker must receive the same `STREAMIOV_VOICE_SIGNING_KEY` (at least 32 bytes) through their secret managers. Never commit the key or place it in the desktop client.

The desktop first POSTs `/v1/voice/ticket` with the bearer token. The Worker validates the signature and claims; the Durable Object atomically consumes the JWT `jti` to reject token replay, then issues a random, one-use WebSocket ticket that expires after 60 seconds. The WebSocket URL contains only that one-use ticket, not the reusable room JWT.

## Routes

- `GET /health` — reports whether the secret and Durable Object binding are configured.
- `POST /v1/voice/ticket` — exchange a room JWT for a one-use WebSocket ticket.
- `GET /v1/voice/rooms/{roomId}` — WebSocket upgrade.
- `POST /v1/voice/rooms/{roomId}/close` — owner-token-only room shutdown, revoking outstanding tickets and closing active sockets.

Durable Object state is isolated by room. The service caps rooms at eight connected participants and 90 signalling/control messages per participant per minute. It limits message size, validates message types and SDP/ICE payloads, and forwards offers, answers, ICE candidates and mute/deafen/speaking state only to room participants.

## Deployment boundary

No Worker, Durable Object, DNS route, production secret or Cloudflare resource is created or changed by this repository patch. Before deployment, configure `STREAMIOV_VOICE_SIGNING_KEY` in both the Core host and this Worker, configure `STREAMIOV_VOICE_ALLOWED_ORIGINS` for the exact public Studio origins, provision the Durable Object migration, and verify two authenticated clients end-to-end. This worker is signalling only; it is not an SFU/TURN relay. Direct peer connectivity can fail behind restrictive NATs until a self-hosted TURN relay is provided. No paid relay is configured.
