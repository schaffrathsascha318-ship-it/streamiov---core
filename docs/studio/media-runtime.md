# STREAMIOV Studio media runtime coordinator

This package establishes the lifecycle contract between the Studio scene graph,
audio mixer, encoder and RTMP/RTMPS output adapters.

## Safety and status contract

- The coordinator does not claim to capture devices, composite frames or encode media. Those capabilities must be supplied by concrete native adapters.
- A successful output connection request is not proof of a live stream. The runtime enters `live` only when the output adapter returns `true` from `isActive()` or an authoritative adapter event calls `confirmOutputActive(true)`.
- Transport loss immediately removes LIVE status and moves the runtime to `reconnecting`.
- Stream keys are passed directly to the output adapter and are never included in snapshots or error messages. Adapters must not log their arguments.
- Destination URLs must use RTMP/RTMPS and may not embed username/password credentials.
- Shutdown attempts every adapter even if an earlier adapter fails.

## Adapter interfaces

- `compositor.start({ sceneGraph, mode: "preview" })`, `compositor.stop()`
- `mixer.start()`, `mixer.stop()`
- `encoder.start({ profile })`, `encoder.stop()`
- `output.connect({ destination, streamKey })`, `output.isActive()`, `output.disconnect()`

Concrete capture, frame composition, audio routing, encoding, network transport,
device hot-plug, reconnection policy and hardware acceleration remain separate
deliverables. This coordinator is not a production encoder or a TikTok approval.
