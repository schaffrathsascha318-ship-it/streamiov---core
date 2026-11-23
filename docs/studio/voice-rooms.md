# STREAMIOV Voice – rooms, access and peer transport

## Implemented in this branch

- Persistent SQLite room, membership and invitation records in a separate `voice-rooms.sqlite3` database.
- Account-session-protected Core routes for room creation, invitation, joining, short-lived token refresh and owner closure.
- Random invite codes are stored only as SHA-256 hashes, are expiry-limited, use-limited and revocable when a room closes.
- The Core issues 5-minute HS256 room-scoped tokens only after verifying active membership. The HMAC key is runtime-only.
- A Cloudflare Durable Object Worker validates those tokens, exchanges them for 60-second one-use WebSocket tickets, rate-limits signalling, caps each room at eight connected participants, and forwards only SDP/ICE and participant state.
- Electron keeps reusable bearer tokens in the main process. The renderer receives only a one-use WebSocket ticket.
- The Studio client establishes peer-to-peer WebRTC audio, sends processed microphone audio from the Studio mixer, supports mute/deafen and push-to-talk, and routes remote participants to the headphones bus.
- Room closure revokes stored membership/invites and asks the signalling Worker to close active WebSockets. The UI reports when the Worker could not be reached.
- No audio recording or server-side media relay is implemented.

## Runtime configuration

Configure the same random secret (at least 32 bytes) separately in the private Core host and Cloudflare Worker:

- `STREAMIOV_VOICE_SIGNING_KEY` — HMAC-SHA256 signing key; never commit it.
- `STREAMIOV_VOICE_SIGNALING_URL` — HTTPS origin of the deployed Voice Worker, e.g. `https://voice.example.invalid` (replace with the actual deployed origin).

Worker configuration:

- `STREAMIOV_VOICE_SIGNING_KEY` — same value as the Core secret.
- `STREAMIOV_VOICE_ALLOWED_ORIGINS` — comma-separated exact HTTPS origins for browser clients. Native desktop WebSocket clients use a one-use 60-second ticket and do not send an Origin header.

Deploy the Durable Object migration before enabling the service. Do not reuse the AI Worker token, TikTok OAuth secret, or any platform credential as the Voice signing key.

## Transport and limitations

The current implementation is a peer-to-peer WebRTC mesh with a public STUN discovery fallback. The signalling Worker never receives media. There is no TURN relay/SFU in this branch. Direct connectivity can fail behind symmetric NAT, restrictive firewalls, or networks that block UDP; a real public Voice launch therefore requires a separately operated, authenticated TURN relay and two-client real-network acceptance. No third-party paid relay is configured.

The room UI requires an authenticated Streamiov account, an active local microphone capture, a deployed Worker and configured secrets. It defaults to push-to-talk and headphones-only remote playback to reduce acoustic feedback. The system does not automatically record calls. Screen/system audio and music are not sent to Voice peers.

## Deployment / verification boundary

This is source implementation only. The Worker has not been deployed, secrets have not been configured, the Core host has not been started with the required Voice settings, and two real clients have not completed an end-to-end call. Therefore Voice must remain labelled **IMPLEMENTED — DEPLOYMENT AND TWO-CLIENT VERIFICATION REQUIRED**, not production-ready.
