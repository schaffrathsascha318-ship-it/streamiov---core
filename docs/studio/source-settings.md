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

This makes source configuration persistable, but it does not yet connect every source type to the production compositor. Device discovery, actual frame capture and Program/Encoder routing remain separate integration work.

Run `npm run test:engine`.
