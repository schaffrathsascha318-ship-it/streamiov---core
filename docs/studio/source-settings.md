# STREAMIOV Studio source settings

The source model now persists a small, type-specific settings object instead of silently dropping device and capture selections.

Supported fields:

- Camera: opaque `deviceId`, width, height and frame rate.
- Microphone/audio: opaque `deviceId`.
- Screen/window/capture: ephemeral source ID, display ID, width, height and frame rate.
- Image/video: internal asset ID and loop flag.
- Text: bounded text, font size and hex color.
- Color: hex color.

Unknown fields and invalid values reject the whole update. The model does not accept arbitrary paths, URLs, executable commands or secrets. Opaque device/source IDs are local references and can become stale after device changes; adapters must re-enumerate and validate them before opening a capture stream.

`engine/source-contract.js` is now the single contract shared by the metadata model, scene engine and Regie. Legacy `capture` sources are normalized to `screen`, `title` cards are first-class, and saved camera/display/asset references are validated against the current local inventory before a runtime is opened. The source list shows `connecting`, `ready`, `stale`, `permission-denied`, `device-busy`, `ended` or `error`, offers a reselect/retry action for unhealthy sources, and clears runtimes when a track ends.

This makes source configuration persistable and locally recoverable. It does not prove physical camera/display availability, platform permission or live output; those remain external device and platform acceptance. Local frame capture, Program routing and RTMP output are implemented but only verified with local tests in this environment.

Run `npm run test:engine` and `python3 -m unittest tests.test_studio_scene_ui`.
