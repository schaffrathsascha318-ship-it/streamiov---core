# STREAMIOV Studio audio routing

The local mixer exposes independent MediaStream output buses instead of forcing every source into one inseparable output:

- `stream`: combined programme mix intended for the encoder.
- `monitor`: separate local-monitor bus, not yet connected to a physical output device.
- `microphone_stem`, `music_stem`, `game_stem`, `alerts_stem`, `tts_stem`: isolated per-source outputs for independent capture/processing.

Every channel has its own gain and mute state and can be routed to one or more buses with `connect(..., { routes })` or `setRoutes(channel, routes)`. The same source is never implicitly copied into every bus. The microphone currently routes to the programme mix, monitor bus, and its isolated stem. The other named stems are provisioned but have no active source yet.

The mixer only produces local MediaStreams. It does not connect physical speakers, GStreamer, RTMP, or TikTok. No audio is transmitted and no LIVE state is implied. TikTok OAuth and token handling remain untouched.

Run `npm run test:engine`.
