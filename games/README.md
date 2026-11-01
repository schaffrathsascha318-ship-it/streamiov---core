# STREAMIOV Games

STREAMIOV games are independent products. Each game owns its source, manifest, tests, version, readiness state and release history. A game must never require another game to be installed or running.

## Release states
- planned: concept only; not playable and not distributable.
- development: source is being built; not publicly released.
- automated_tests_passed: automated checks pass; human gameplay verification is still required.
- gameplay_verified: a tester has completed the documented gameplay checklist on supported devices.
- released: a versioned public release exists and its download is available.

Automated tests alone never promote a game to gameplay_verified. A game can be released independently once its own release gates pass; the full STREAMIOV ecosystem launch remains a separate decision.

## First game
Neon Relay is the first independent arcade prototype. It is self-contained, has no external runtime dependencies and supports keyboard and pointer/touch input. It remains in development until real gameplay testing is recorded.

Every game must include a manifest, actual game implementation, rules and controls, verification checklist, and runtime-appropriate automated tests. Never mark a game released because its files merely exist or because CI passed.