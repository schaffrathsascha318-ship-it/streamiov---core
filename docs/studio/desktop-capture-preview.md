# STREAMIOV Studio desktop/window capture preview

The Regie can enumerate local screen and window sources through Electron's trusted main-process `desktopCapturer` bridge and preview one selected source through Chromium's desktop media capture constraints.

- Source enumeration is restricted to the trusted top-level Studio document.
- Only source ID, bounded display name, type and display ID are returned to the renderer; thumbnails and native objects are not exposed.
- The selected stream remains local and is stopped on user action or window close.
- The current preview is not yet connected to the scene compositor, Program output, audio mixer or encoder. It does not indicate LIVE.
- Device/source availability depends on the operating system, desktop session and permissions. Linux Wayland/PipeWire and ChromeOS/Crostini require separate real-device validation.

The contract test runs through `npm run test:engine`. Build success is not a hardware capture acceptance test.
