# Twitch account connection

Streamiov uses Twitch's official OAuth and Helix API. It does not ask the streamer to paste an RTMP URL or stream key.

## Twitch developer application

Register a Twitch developer application and configure this exact OAuth redirect URL:

`http://127.0.0.1:43821/callback`

The application must use the Authorization Code flow. Streamiov requests only the scope needed to retrieve the broadcaster's own stream key:

- `channel:read:stream_key`

## Local protected configuration

Provide these environment variables to the Streamiov Studio main process through the protected local secret configuration (never commit them):

- `STREAMIOV_TWITCH_CLIENT_ID`
- `STREAMIOV_TWITCH_CLIENT_SECRET`
- `STREAMIOV_TWITCH_TOKEN_ENCRYPTION_KEY`: base64 encoding of exactly 32 random bytes
- `STREAMIOV_TWITCH_REDIRECT_URI` (optional; defaults to the exact redirect URL above)

The OAuth token is encrypted at rest in the operating system's Streamiov user-data directory. The stream key is fetched on demand from Twitch Helix when the output is prepared and again when LIVE starts; it is not persisted, returned to the renderer, or written to logs.

## Important limits

- A Twitch login without the `channel:read:stream_key` grant cannot produce an output destination.
- Twitch may deny access if the channel is not permitted to stream; Streamiov reports the denial instead of fabricating a key.
- Encoder initialization is not proof that Twitch accepted the stream or that the channel is LIVE. Remote platform confirmation remains a separate state.
- TikTok's sandbox Login Kit permission is not a documented production RTMP-key retrieval API. Streamiov must not use private or reverse-engineered endpoints to obtain TikTok stream credentials.
