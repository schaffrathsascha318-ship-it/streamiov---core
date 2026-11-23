# STREAMIOV Voice – rooms, access and peer transport

## Implemented in this branch

- Persistent SQLite room, membership and invitation records in a separate `voice-rooms.sqlite3` database.
- Account-session-protected Core routes for room creation, invitation, joining, short-lived token refresh and owner closure.
- Random invite codes are stored only as SHA-256 hashes, are expiry-limited, use-limited and revocable when a room closes.
- The Core issues 5-minute HS256 room-scoped tokens only after verifying active membership. The HMAC key is runtime-only.
- A Cloudflare Durable Object Worker validates those tokens, exchanges them for 60-second one-use WebSocket tickets, rate-limits signalling, caps each room at eight connected participants, and forwards only SDP/ICE and participant state.
- Electron keeps reusable bearer tokens in the main process. The renderer receives only a one-use WebSocket ticket.
- The Studio client establishes peer-to-peer WebRTC audio, sends processed microphone audio from the Studio mixer, supports mute/deafen and push-to-talk, and routes remote participants to the headphones bus.
- Room closure revokes stored membership/invites and asks the signalling Worker to close active WebSockets and invalidate pending one-use tickets. The UI reports when the Worker could not be reached.
- No audio recording or server-side media relay is implemented.

## Runtime configuration

Configure the same random secret (at least 32 bytes) separately in the private Core host and Cloudflare Worker:

- `STREAMIOV_VOICE_SIGNING_KEY` — HMAC-SHA256 signing key; never commit it.
- `STREAMIOV_VOICE_SIGNALING_URL` — HTTPS origin of the deployed Voice Worker, e.g. `https://voice.example.invalid` (replace with the actual deployed origin).

Core configuration:

- `STREAMIOV_VOICE_SIGNING_KEY` — HMAC signing key shared with the signalling Worker.
- `STREAMIOV_VOICE_SIGNALING_URL` — deployed HTTPS origin of the Worker.
- `STREAMIOV_TURN_URLS` — optional comma-separated `turn:`/`turns:` URLs.
- `STREAMIOV_TURN_SHARED_SECRET` — optional coturn REST shared secret, same value as `static-auth-secret`; at least 32 bytes.

The host systemd unit reads the optional private file `/etc/streamiov/voice.env`. Create it with the real values (do not commit it):

```ini
STREAMIOV_VOICE_SIGNING_KEY=REPLACE_WITH_RANDOM_VOICE_SIGNING_SECRET
STREAMIOV_VOICE_SIGNALING_URL=https://REPLACE_WITH_DEPLOYED_WORKER_ORIGIN
STREAMIOV_TURN_URLS=turn:REPLACE_WITH_VOICE_DOMAIN:3478?transport=udp,turns:REPLACE_WITH_VOICE_DOMAIN:5349?transport=tcp
STREAMIOV_TURN_SHARED_SECRET=REPLACE_WITH_DIFFERENT_RANDOM_TURN_SECRET
```

Protect the file with `root:streamiov` ownership and mode `0640`, then reload/restart the host service. Use a different random secret for Voice JWT signing and coturn REST credentials. The same TURN secret belongs in coturn's protected `static-auth-secret` setting; the Voice signing key belongs in the Worker secret store.

Worker configuration:

- `STREAMIOV_VOICE_SIGNING_KEY` — same value as the Core secret.
- `STREAMIOV_VOICE_ALLOWED_ORIGINS` — comma-separated exact HTTPS origins for browser clients. Native desktop WebSocket clients use a one-use 60-second ticket and do not send an Origin header.

Deploy the Durable Object migration before enabling the service. Do not reuse the AI Worker token, TikTok OAuth secret, or any platform credential as the Voice signing key.

## Transport and limitations

The current implementation is a peer-to-peer WebRTC mesh. It always includes a public STUN discovery fallback and can optionally issue short-lived coturn REST credentials from Core when both `STREAMIOV_TURN_URLS` and `STREAMIOV_TURN_SHARED_SECRET` are configured. The Core generates a one-hour username/credential pair using HMAC-SHA1 as required by coturn REST authentication; the shared secret is never sent to the renderer. A self-hosted coturn template is in `infrastructure/voice/coturn/turnserver.conf.example`.

To enable a self-hosted relay on Debian/Ubuntu: install coturn with `sudo apt install coturn`; copy the template to `/etc/turnserver.conf`; replace the domain, certificate paths, public IP mapping (if behind NAT), and `static-auth-secret`; use a separate random TURN secret (for example `openssl rand -hex 32`) and set the same value as `STREAMIOV_TURN_SHARED_SECRET` in the protected Core environment file. Protect coturn's config with `root:turnserver` ownership and mode `0600`, enable the coturn service, and open UDP/TCP 3478, TCP 5349, and the configured UDP relay range (default 49160–49200). Do not use a public static TURN credential in the desktop app.

The signalling Worker never receives media and is not an SFU. Without a configured and reachable TURN server, direct connectivity can still fail behind symmetric NAT, restrictive firewalls, or networks that block UDP. No third-party paid relay is configured.

The room UI requires an authenticated Streamiov account, an active local microphone capture, a deployed Worker and configured secrets. It defaults to push-to-talk and headphones-only remote playback to reduce acoustic feedback. The system does not automatically record calls. Screen/system audio and music are not sent to Voice peers.

## Deployment / verification boundary

This is source implementation only. The Worker and TURN relay have not been deployed, secrets/domain/certificates/firewall rules have not been configured, the Core host has not been started with Voice settings, and two real clients have not completed an end-to-end call. Therefore Voice must remain labelled **IMPLEMENTED — DEPLOYMENT AND TWO-CLIENT VERIFICATION REQUIRED**, not production-ready.
