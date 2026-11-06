# STREAMIOV Audio Engine – Integrationsplan

Status: architecture/inventory note; no runtime capability is claimed by this document.

## Verified repository baseline

This plan is based on the currently open Draft PRs and Issues listed below. Their code is **not merged into `main`** unless separately stated. Treat each branch as proposed work and reconcile dependencies before combining changes.

| Work | What the reviewed change currently provides | What it does not prove |
|---|---|---|
| PR #113 – independent output contract | Four persisted logical outputs (stream, monitor, headphones, communications), per-output volume/mute/device ID, source route matrix, Electron IPC and UI | No physical output binding, native mixer, real four-output isolation, or encoder feed |
| PR #89 – source channel controls | Web Audio mixer with stream/monitor MediaStreamDestination buses; real microphone capture, local music/alert files, generated TTS WAV, optional desktop loopback; monitor can use `setSinkId` | No independent physical headphones/communications outputs; no native device lifecycle; no encoder integration or hardware acceptance |
| PR #87 – microphone mixer | Earlier mixer/source implementation; overlaps the mixer files in PR #89 | Do not merge both implementations independently without reconciling their shared files |
| PR #82 – compositor/mixer smoke test | GStreamer compositor + audiomixer graph with synthetic test sources; CI can generate WebM test output | Does not connect live capture sources, the Studio mixer, a production encoder, or TikTok LIVE |
| PR #81 – runtime lifecycle | Lifecycle contract; LIVE depends on a positive output-adapter confirmation | Does not implement capture, mixing, encoding, or transport itself |
| Issue #40 – media pipeline | Defines real capture, compositor, mixer, encoder, RTMP/RTMPS and A/V sync acceptance | Still open; synthetic pipeline is not a production stream |
| Issue #114 – native audio and STREAMIOV Voice | Defines device handling, buses, processing, voice rooms, security and hardware acceptance | Still open; no verified two-client voice room or hardware acceptance |

## Integration decision

1. Keep PR #113 as the persisted user-preference contract. Its `configuration_only` and `not_connected` states must remain truthful until a real adapter confirms device opening and active audio flow.
2. Reuse the Web Audio channel graph from PR #89 as a local capture/mixing prototype where appropriate. Do not mistake its current `stream` and `monitor` buses for the four independent physical outputs in #113.
3. Reconcile PR #87 and #89 before merging either: both change `engine/audio-mixer.js`, `main.js`, `preload.js`, and the Regie UI. Select one canonical implementation and preserve tests from both where still relevant.
4. Keep GStreamer smoke tests from PR #82 as deterministic CI coverage. Add a separate adapter that consumes the actual Stream bus; do not replace synthetic tests with hardware-dependent CI.
5. Keep #81 as the lifecycle/status authority. Only report `DEVICE_CONNECTED` after opening the selected device, `ROUTING_ACTIVE` after frames are flowing through the intended bus, and `VERIFIED` only after independent loopback/measurement and required integration checks.

## Required engine shape

- A platform-neutral engine contract owns source registration, bus registration, routing, gain/mute/solo/pan, meters, clipping, timestamps, device-loss events and shutdown.
- Platform adapters own enumeration, stable device identity, open/close, hot-plug and native output. A browser `enumerateDevices()` result is discovery metadata, not proof that a device is open.
- Logical buses remain distinct: `stream`, `monitor`, `headphones`, `communications`. Each output has its own sink and independent gain/mute stage. A shared mix routed to multiple sinks is not equivalent to independently controlled outputs.
- Source routing must allow an explicit empty route set (silence) as well as one or more valid buses. Validate source IDs, bus IDs, device IDs and boolean fields strictly.
- The encoder consumes only the Stream bus. Monitor, headphones and communications are excluded unless a user explicitly routes a source to Stream. Voice is excluded from Stream by default.
- Device loss must transition the affected output to a non-active state, detach safely, and recover only after a new device is opened and audio flow is confirmed.
- Never expose stream keys, voice access tokens or credentials in renderer state, diagnostics or logs.

## Implementation sequence

### Phase A – reconcile and test the existing prototype
- Compare PR #87 and #89 file-by-file; settle on one canonical mixer implementation.
- Add strict validation for mute booleans and route arrays; support intentional empty routes.
- Add tests for per-output isolation, zero-route silence, route changes while active, cleanup, and device-loss handling.
- Keep all physical adapter status values disconnected until the adapter exists.

### Phase B – implement real output adapters
- Start with Windows 11 x64.
- Define adapter methods for enumerate/open/write-or-attach/close and capability reporting.
- Open and verify four independently addressable outputs where the OS and device topology permit. If a platform cannot expose four independent endpoints, report the exact capability limitation rather than simulating it.
- Test hot-plug, default-device changes, format/sample-rate changes, permission denial, and recovery.

### Phase C – connect media and encoder
- Route real microphone, music, desktop/game capture, alerts and TTS into source channels.
- Bridge the Stream bus into the media pipeline in #40 with explicit sample-rate/channel conversion and timestamps.
- Verify Monitor/Headphones/Communications cannot leak into Stream.
- Keep #82's synthetic GStreamer graph as a fast deterministic test; add adapter/integration tests separately.

### Phase D – voice and platform expansion
- Implement authenticated, short-lived room access and encrypted transport with rate limits and abuse controls.
- No recording by default; any opt-in recording requires clear consent and a separate privacy/legal review.
- Test two real clients, mute/deafen, per-participant gain, push-to-talk, reconnect and Voice-to-Stream exclusion.
- Add Linux and ChromeOS adapters with independent capability and hardware evidence; mobile reports capabilities honestly.

## Release gates

- Unit and integration tests pass; no hardware result is inferred from CI alone.
- Four output paths are independently measured on Windows 11 x64 hardware.
- Encoder input is demonstrably only the Stream bus.
- Device-loss/reconnect, latency, clipping and A/V sync are measured.
- Voice acceptance is demonstrated with two real clients and privacy/security review.
- No TikTok OAuth/security, Cloudflare production, deployment, publishing or merge is part of this work.

## References

- [PR #113 – output configuration contract](../../pull/113)
- [PR #89 – source channel controls](../../pull/89)
- [PR #87 – microphone mixer prototype](../../pull/87)
- [PR #82 – compositor/mixer smoke test](../../pull/82)
- [PR #81 – media runtime lifecycle](../../pull/81)
- [Issue #40 – real media pipeline](../../issues/40)
- [Issue #114 – native audio and STREAMIOV Voice](../../issues/114)
