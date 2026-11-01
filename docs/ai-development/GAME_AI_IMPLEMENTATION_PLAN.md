# Streamiov Game AI — implementation plan

The authoritative role contract is `ai/specialists/game/README.md`.

## Integration location

Implement this as a dedicated specialist under the shared AI runtime/provider architecture, not as a second model server and not inside the public Pages homepage. The specialist owns game-specific prompts, tool permissions, workflows, test fixtures, and project records. It calls the existing configured Streamiov model provider through the common provider interface.

## Phased delivery

### G1 — Specialist registration
- Register `game` as a named specialist with the contract in `ai/specialists/game/README.md`.
- Give it a scoped game workspace and explicit tools for reading/writing game project files, running approved tests, and recording evidence.
- Keep it isolated from OAuth, secrets, payment, account, and production deployment data.

### G2 — Original game production
- Create a project manifest and reproducible build/test commands.
- Support an original 2D vertical slice first, then a 3D prototype when the engine/toolchain is available.
- Require playability and gameplay verification in addition to unit tests.

### G3 — Retro discovery and rights gate
- Build a metadata-only discovery catalogue for dormant, delisted, unsupported, or discontinued titles.
- Store sources and dates; do not download or reuse game binaries/assets.
- Produce per-title, per-activity rights dossiers and conservative statuses from the role contract.
- Unknown rights must block use of protected material; offer a clean-room original alternative.

### G4 — Remaster/remake/sequel production
- Enable each activity only for the exact scope covered by documented rights.
- Preserve third-party attribution and licence obligations.
- Re-run rights checks before packaging and release.

### G5 — Release quality
- Automated build, unit, integration, compatibility, accessibility, security, and asset-provenance checks.
- Human gameplay verification and release review.
- Release manifest, checksums, version, platform matrix, and evidence archive.

## Current status

This file records the approved target architecture and acceptance criteria. It does not claim the specialist is registered, autonomous, connected to a rights database, or able to publish games yet. Those capabilities must be implemented and tested in the phases above.
