# OpenCode Core platform support

## Product requirement

OpenCode Core is intended to cover the full range of development devices, not only desktop Linux or Windows. The shared task engine, queue format, specialist contracts, and provider interface should remain platform-neutral. OS-specific filesystem, process, credential, packaging, and device integration belongs behind explicit adapters.

A device can be either:
- a **Core host**, which runs the worker service and owns the workspace and persistent state; or
- a **client/control device**, which connects to a Core host over an authenticated API.

A phone or tablet does not need to run the full worker service locally to be a supported device. It must be able to securely control and inspect a Core host through a supported client.

## Target coverage

| Device / OS | Intended role | Architecture targets | Current evidence |
|---|---|---|---|
| Windows 10/11 desktop and laptop | Host and client | x64 first; ARM64 where dependencies permit | Windows x64 and ARM64 CI verify wheel installation, CLI startup, and handle-relative workspace read/create/edit/list operations. Tests reject junction/reparse-point escapes and traversal. Real Windows hardware verification remains a release gate. |
| Linux desktop, laptop, and server | Host and client | x86_64 and aarch64 | Ubuntu 24.04 x64 and ARM64 CI run the full Python suite and wheel/CLI smoke test. Other distributions need dedicated packaging tests. |
| macOS desktop and laptop | Host and client | Apple Silicon arm64; Intel x86_64 where supported | macOS 15 Apple Silicon and Intel CI run the full Python suite and wheel/CLI smoke test. Real hardware and signing/notarization remain unverified. |
| ChromeOS / Chromebook | Primarily client; optional Linux host through Crostini where supported | Device CPU architecture | No dedicated ChromeOS hardware CI yet. Crostini is a Linux compatibility route, not proof of native ChromeOS support. |
| Android phone and tablet | Client/control device; optional local lightweight tools | arm64; additional ABIs subject to testing | No Android app or device verification is claimed yet. |
| iPhone and iPad | Client/control device | Apple mobile architectures | No iOS app or device verification is claimed yet. |

## Architecture requirements

1. Keep the task engine and provider contracts independent of OS-specific APIs.
2. Implement filesystem access through platform backends with equivalent security guarantees. Do not replace handle-relative checks with path-only checks or disable symlink/reparse-point protections.
3. Keep long-running workers and persistent SQLite state on a trusted Core host. Mobile clients should use an authenticated, encrypted control API rather than exposing workspace files or model credentials directly.
4. Separate UI/client packaging from worker-host packaging. A supported client does not imply that the full worker service can run locally on that device.
5. Report unavailable capabilities explicitly and fail closed. Never label a platform fully supported based only on a successful package build.

## Release gates by platform

A platform is production-supported only after all relevant checks pass:
- package installs and launches on the target OS and architecture;
- filesystem traversal, symlink/reparse-point, root replacement, path traversal, and race tests pass for host platforms;
- worker lifecycle, process shutdown, database recovery, and permissions are tested;
- client authentication, reconnect, offline state, and authorization are tested for client platforms;
- real hardware verification is recorded for at least one representative device per supported architecture;
- release artifacts, update path, and platform-specific security/signing requirements are verified.

## Client/API readiness

The local host now exposes one-time device pairing, device enrollment, owner-side device listing/revocation, and a scoped device status endpoint. Device credentials are stored as hashes, expire after 90 days, can be revoked, and currently receive only `status:read`. Remote enrollment requires TLS; loopback enrollment is allowed for local development. Task submission/control, workspace access, native OpenCode Core clients, and device reconnect/offline UX are not implemented. ChromeOS, Android, and iOS remain product targets, not released or verified Core clients. The separate Streamiov Studio PWA is not evidence of OpenCode Core client support.

Before remote task control is enabled, implement narrowly scoped task queue endpoints, task ownership/authorization, durable audit records, request idempotency, cancellation semantics, and reconnect/offline behavior. Provider credentials and direct workspace access must remain on the trusted Core host.

## Current status

Linux x86_64 CI covers Python 3.10, 3.12, and 3.13; Linux aarch64 runs the full Python suite and wheel/CLI smoke test on Python 3.12. Windows x64 and ARM64 CI verify wheel installation, CLI startup, and handle-relative workspace operations with junction/traversal rejection tests. macOS 15 CI runs the full Python suite and wheel/CLI smoke test on Apple Silicon and Intel. The device-pairing API is covered by host integration tests, but no native client is released. Real-device verification and signing/notarization remain separate release gates. ChromeOS, Android, and iOS remain explicit targets but are not yet verified or released as native clients.

No platform is considered fully complete until its relevant release gates are evidenced.
