# Native StreamioV game runtime

This template is the source for five independent Godot 4.7.2 game projects. The generated projects are native downloadable games, not browser games.

## Targets

- Windows 11 x64: standalone EXE with embedded game data.
- Linux x86_64 and ARM64: standalone native executables with embedded game data.
- Android phones and tablets: ARM64 APK for sideload testing.
- ChromeOS: ARM64 APK for ARM Chromebooks or x86_64 APK for Intel Chromebooks with Android support; Linux x86_64/ARM64 executable inside compatible Crostini environments.
- iPhone/iPad: unsigned Xcode project ZIP. A valid Apple Developer signing identity and provisioning profile are required before installation; CI does not claim a signed IPA.

The Android APK generated in CI is a debug/test build, not a signed public release. Desktop builds are not code-signed. No paid SDK, service, API, or external runtime provider is required.

## Generate projects

From the repository root:

    python3 scripts/generate-native-games.py

This creates one Godot project per game under games/native/. Each project has its own game ID, title, export presets, and standalone build outputs. The shared source runtime is games/native-template/main.gd.

## Export

Install Godot 4.7.2 and its matching export templates, plus the Android SDK/JDK 17 for Android. Then use the project presets:

    godot --headless --editor --path games/native/neon-relay --quit
    godot --headless --path games/native/neon-relay --export-release "Windows Desktop x64" build/neon-relay.exe
    godot --headless --path games/native/neon-relay --export-release "Linux x64" build/neon-relay\n    godot --headless --path games/native/neon-relay --export-release "Linux ARM64" build/neon-relay-arm64\n    godot --headless --path games/native/neon-relay --export-debug "Android x86_64" build/neon-relay-x64.apk
    godot --headless --path games/native/neon-relay --export-debug "Android ARM64" build/neon-relay.apk

The CI workflow builds all five games for Windows, Linux and Android/ChromeOS, and exports unsigned iOS Xcode projects on macOS. CI artifacts are development builds; they do not prove physical-device gameplay, accessibility, or release readiness.
