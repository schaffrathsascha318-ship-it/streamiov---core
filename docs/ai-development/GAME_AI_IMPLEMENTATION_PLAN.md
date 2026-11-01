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
- Support original 2D and 3D games, plus a dedicated 2D-to-3D modernization path for rights-cleared legacy games. Assess full 3D versus 2.5D and whether an optional classic 2D mode is appropriate; build real 3D environments, models, camera, lighting, animation, and adapted gameplay rather than applying a superficial 3D filter.
- Require playability and gameplay verification in addition to unit tests.

### G3 — Retro discovery and rights gate
- Build a metadata-only discovery catalogue for dormant, delisted, unsupported, or discontinued titles.
- Store sources and dates; do not download or reuse game binaries/assets.
- Produce per-title, per-activity rights dossiers and conservative statuses from the role contract.
- Unknown rights must block use of protected material; offer a clean-room original alternative.

### G4 — Remaster/remake/sequel production
- Enable each activity only for the exact scope covered by documented rights, including a separate explicit permission check for adapting a 2D title into 2.5D/3D.
- Preserve third-party attribution and licence obligations.
- Re-run rights checks before packaging and release.

### G5 — Release quality
- Automated build, unit, integration, compatibility, accessibility, security, and asset-provenance checks.
- Human gameplay verification and release review.
- Release manifest, checksums, version, platform matrix, and evidence archive.

## Current status

This file records the approved target architecture and acceptance criteria. The Game AI must modernize eligible 2D classics into genuine 3D experiences as well as create original 2D/3D games. It does not claim the specialist is registered, autonomous, connected to a rights database, or able to publish games yet. Those capabilities must be implemented and tested in the phases above.


### G0 — Original idea and ownership foundation
- Build a Streamiov-original idea pipeline that proposes, scores for feasibility/originality, versions, and records original mechanics, worlds, characters, stories, levels, and game concepts before implementation.
- Maintain a provenance ledger from concept to release: dated briefs and versions, source commits, contributor/asset origins, AI tool/provider and applicable terms, third-party inputs, licences, and approvals.
- Add a standard Streamiov intro and outro/closing credits to every Streamiov-created game, with configurable skip/short behavior, accessible presentation, and no disruptive gameplay interruption. Include an in-game credits/about screen and accurate Streamiov-original branding.
- Gate “owned by Streamiov” claims on verified rights in all contributions and components, including contributor assignments/agreements, AI tool terms, fonts, music, middleware, assets, and open-source licences. Record exclusions, licence scope, attribution, and the actual rights holder.
- Copyright notices, branding, intro/outro, hashes, and provenance are evidence/identification measures, not substitutes for ownership transfers or legal/technical copy protection. Never claim ownership of third-party or uncleared material.


## Required rights-research and recordkeeping capability

The Game AI must own a repeatable evidence workflow, not just a rights checklist in documentation:

- Research official legal texts and registers for the selected territory and save source URL, authority, access timestamp, relevant provision/register entry, and a concise evidence note.
- Separate copyright term expiry from a contract/licence expiry and from trademark/design/patent status. A commercial licence ending does not make the underlying work free to reuse.
- Calculate possible public-domain status from authorship, co-authorship, work type, publication facts, and territorial rules; preserve the calculation and flag uncertainty.
- Check names/logos and other rights separately. Permit new editions/remakes/sequels only for elements and activities actually cleared in the relevant territories; create clean-room replacements for uncleared names, characters, artwork, music, code, and story elements.
- Write both a machine-readable rights record and a readable dossier. Re-check before release and when scope or law changes. Block affected assets/actions while evidence is incomplete; require qualified human legal review for ambiguous cases.
- A completed dossier is not a legal opinion or a guarantee. The release gate must display the precise evidence and any human approval, not merely a green boolean.

For Germany, the AI should use current official legal sources as a starting point—for example, UrhG §§ 64–65 for general and joint-author copyright terms and MarkenG § 47 plus DPMA register guidance for registered-mark duration/renewal—then verify the applicable rules for each other territory. Do not hard-code one country's term as a worldwide rule.
