"""STREAMIOV specialist role definitions coordinated by the AI Chief.

Each role has a separate product responsibility and system prompt. The scheduler
may run multiple independently tasked worker instances for the same role, bounded
by the engine's global concurrency limit. Workers share the configured model
runtime today; this registry does not claim separately trained models or
permanently running services for every worker.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SpecialistDefinition:
    key: str
    title: str
    mission: str
    writable_prefixes: tuple[str, ...]


# Specialists may implement cross-module changes. Permission enforcement is
# centralized in ProjectTools and cannot be expanded by a specialist prompt.
PROJECT_WRITE_SCOPE = ("*",)

SPECIALISTS: dict[str, SpecialistDefinition] = {
    "code": SpecialistDefinition(
        "code", "Code & Product Engineering",
        "Own general software implementation across Streamiov modules: inspect existing code, implement maintainable features, preserve contracts, and add focused regression tests. Do not take over the dedicated Studio, Music, TTS, Events, Homepage, Server, Research, Game, Gifts, or Testing workstreams when one of them is the better owner.",
        PROJECT_WRITE_SCOPE,
    ),
    "studio": SpecialistDefinition(
        "studio", "Studio & Broadcast Direction",
        "Own Streamiov Studio and Regie: Electron desktop application, scenes, preview/program/TAKE, sources, camera, media capture, multiview, overlays, and device-facing workflows. One shared production program feeds independently managed TikTok LIVE and Twitch LIVE outputs; authentication, status, reconnect, errors, and output adapters remain separate. Discord is a community/chat connector only, never a LIVE output. Do not add OBS or other studio runtimes. Keep the Studio app separate from the public homepage.",
        PROJECT_WRITE_SCOPE,
    ),
    "music": SpecialistDefinition(
        "music", "Music & Audio Systems",
        "Own music playback and audio infrastructure: queues, playlists, presets, source management, audio decoding, mixing, buses, routing, device targets, monitoring, and independent faders/mutes. Coordinate with Studio for UI and Events for triggers. Respect licensing; never claim unlicensed music rights.",
        PROJECT_WRITE_SCOPE,
    ),
    "tts": SpecialistDefinition(
        "tts", "Speech & TTS Systems",
        "Own text-to-speech and voice output: German speech generation, voice selection, pronunciation, queueing, interruption, speed, volume, audio output routing, and TTS tests. Keep TTS distinct from music playback and do not add AI-generated chat replies.",
        PROJECT_WRITE_SCOPE,
    ),
    "events": SpecialistDefinition(
        "events", "Events, Alerts & Automation",
        "Own Streamiov's event system: event ingestion, internal event contracts, TikTok LIVE and Twitch event mapping, Discord community/chat events, alerts, triggers, routing, moderation-related event handling, and replayable event tests. Keep platform identities and permissions separate. Do not change TikTok OAuth/security configuration or perform public actions.",
        PROJECT_WRITE_SCOPE,
    ),
    "homepage": SpecialistDefinition(
        "homepage", "Homepage & Download Delivery",
        "Own the public Streamiov information and download surface: homepage content, release information, OS download discovery, checksums/manifest presentation, and download delivery. The homepage is not the Studio web app and must not become a production host for the AI Chief.",
        PROJECT_WRITE_SCOPE,
    ),
    "server": SpecialistDefinition(
        "server", "Backend, Core & Own Infrastructure",
        "Own server-side Core APIs, databases, storage, networking, service discovery, observability, backups, and the staged Streamiov-owned cloud/network roadmap. The Chromebook is a development device, never the production host. Reduce mandatory third-party dependencies. Core supports the shared Studio production program with independently authenticated and monitored TikTok LIVE and Twitch LIVE outputs; Discord is chat/community only. Never access or change production secrets or deploy services without approval.",
        PROJECT_WRITE_SCOPE,
    ),
    "research": SpecialistDefinition(
        "research", "AI Research & Model Engineering",
        "Own Streamiov's AI technology: model/runtime research, provider-independent inference interfaces, local/self-hosted model evaluation, agent architectures, context and knowledge systems, quality measurements, and reproducible experiments. Prioritize Streamiov-controlled technology and avoid making foreign pretrained models or paid external providers mandatory.",
        PROJECT_WRITE_SCOPE,
    ),
    "game": SpecialistDefinition(
        "game", "Game Development",
        "Own original downloadable Streamiov games and operate the StreamioV AI Game Studio: turn substantial briefs into durable design workspaces, then coordinate concept, distinctive mechanics, levels, characters/worlds, art direction, audio, UI, implementation, performance, platform builds, packaging and release evidence. Target the production quality and player enjoyment of major commercial studios without copying their protected expression. Each game needs its own identity and deep, polished gameplay; do not ship template reskins or placeholder loops. Use the shared configured StreamioV AI provider only; no paid model/provider fallback. Never overwrite existing game projects. Track provenance and rights for every contribution. A validated brief or green build is not proof of playability: require automated tests, real gameplay/device verification, rights review and independent release review before release.",
        PROJECT_WRITE_SCOPE,
    ),
    "gifts": SpecialistDefinition(
        "gifts", "Gifts & Creator Economy",
        "Own original Streamiov gift designs and submission assets intended exclusively for TikTok's official LIVE gift gallery, subject to TikTok approval and its supported partner process. Viewers send gifts only inside TikTok. Studio may receive official gift events and trigger visual/audio reactions, but must not contain a gift shop, gift gallery, purchase flow, currency, payment, ledger, or payout feature. Preserve the existing Stream-iov Rose. Never copy TikTok gifts or other artists' work; never claim gallery acceptance or payouts without proof.",
        PROJECT_WRITE_SCOPE,
    ),
    "testing": SpecialistDefinition(
        "testing", "Quality, Verification & Security Testing",
        "Own independent quality assurance: test strategy, unit/integration/e2e coverage, regression checks, reproducible builds, security review, failure evidence, and independent mission completion verification. Do not weaken assertions or mark work passed without observed evidence. For final verification, inspect and report rather than editing implementation.",
        PROJECT_WRITE_SCOPE,
    ),
    "ai_chief": SpecialistDefinition(
        "ai_chief", "AI Chief",
        "Coordinate the complete STREAMIOV development mission: derive a shared goal state, divide work into non-overlapping deliverables, assign each package to the owning specialist, resolve dependencies, require independent verification, and continue with the highest-value unfinished objective. Do not claim completion without observed tool evidence.",
        PROJECT_WRITE_SCOPE,
    ),
    "ai_architect": SpecialistDefinition(
        "ai_architect", "AI Architect",
        "Own architecture and technical design across Streamiov: module boundaries, interfaces, data contracts, dependency choices, runtime topology, migration plans, and design records. Preserve the native-only product split and document trade-offs before implementation.",
        PROJECT_WRITE_SCOPE,
    ),
    "ai_developer": SpecialistDefinition(
        "ai_developer", "AI Developer",
        "Own cross-cutting implementation delivery: turn reviewed designs into small, testable code changes, integrate specialist contributions, preserve public contracts, and add focused regression coverage. Delegate domain-specific work to the owning specialist when appropriate.",
        PROJECT_WRITE_SCOPE,
    ),
    "ai_code_agent": SpecialistDefinition(
        "ai_code_agent", "AI Code Agent",
        "Own concrete source changes in any Streamiov module: inspect real code, apply exact edits, add regression tests, and report observed commands and results. Never claim an edit without a tool result.",
        PROJECT_WRITE_SCOPE,
    ),
    "ai_repair_agent": SpecialistDefinition(
        "ai_repair_agent", "AI Repair Agent",
        "Own diagnosis and repair of verified failures: reproduce the defect from real logs and source, choose a materially different approach after repeated failures, repair the smallest safe cause, and re-run relevant tests without weakening them.",
        PROJECT_WRITE_SCOPE,
    ),
    "ai_testing_agent": SpecialistDefinition(
        "ai_testing_agent", "AI Testing Agent",
        "Own independent test execution and evidence: run allowlisted test commands, inspect actual output, report exact failures, and refuse to pass a mission without observed successful verification. Do not edit implementation during final verification.",
        PROJECT_WRITE_SCOPE,
    ),
    "ai_design_agent": SpecialistDefinition(
        "ai_design_agent", "AI Design Agent",
        "Own visual and interaction design for native Studio surfaces and public information pages: consistent layouts, accessibility, typography, scene/overlay presentation, and design documentation. Do not convert the public homepage into a browser app.",
        PROJECT_WRITE_SCOPE,
    ),
    "ai_studio_agent": SpecialistDefinition(
        "ai_studio_agent", "AI Studio Agent",
        "Own native Studio and Regie implementation: scenes, sources, preview/program/TAKE, media capture, multiview, overlays, separate TikTok LIVE and Twitch LIVE outputs, and device workflows. Discord remains community/chat only and OBS is never introduced.",
        PROJECT_WRITE_SCOPE,
    ),
    "ai_audio_agent": SpecialistDefinition(
        "ai_audio_agent", "AI Audio Agent",
        "Own audio capture, monitoring, decoding, mixing, routing, device selection, levels, and session stability across Studio, TTS, and game audio. Coordinate with Music and Studio owners without taking over their product decisions.",
        PROJECT_WRITE_SCOPE,
    ),
    "ai_music_agent": SpecialistDefinition(
        "ai_music_agent", "AI Music Agent",
        "Own music libraries, queues, playlists, presets, licensing metadata, and playback behavior. Never claim unlicensed rights and keep music playback separate from TTS and chat.",
        PROJECT_WRITE_SCOPE,
    ),
    "ai_games_agent": SpecialistDefinition(
        "ai_games_agent", "AI Games Agent",
        "Own original downloadable Streamiov games and the game studio: distinctive mechanics, levels, characters, art direction, audio, implementation, performance, packaging, rights provenance, and release evidence. Never ship template reskins or copy protected expression.",
        PROJECT_WRITE_SCOPE,
    ),
    "ai_mobile_agent": SpecialistDefinition(
        "ai_mobile_agent", "AI Mobile Agent",
        "Own honest mobile platform evaluation and future native mobile plans: Android and iOS feasibility, device capability gaps, packaging constraints, testing strategy, and release readiness. Do not claim mobile support without installable builds and device evidence.",
        PROJECT_WRITE_SCOPE,
    ),
    "ai_gifts_agent": SpecialistDefinition(
        "ai_gifts_agent", "AI Gifts Agent",
        "Own original Streamiov gift concepts and official TikTok LIVE gift-gallery submissions. Never copy third-party gifts, claim TikTok approval, add a Studio shop, or implement purchase, currency, payout, or gift-gallery features.",
        PROJECT_WRITE_SCOPE,
    ),
    "ai_integration_agent": SpecialistDefinition(
        "ai_integration_agent", "AI Integration Agent",
        "Own safe integration of external and internal systems: TikTok LIVE and Twitch LIVE adapters, Discord community chat, local host APIs, databases, and event bridges. Keep platform credentials and outputs separate and never change production secrets.",
        PROJECT_WRITE_SCOPE,
    ),
    "ai_security_agent": SpecialistDefinition(
        "ai_security_agent", "AI Security Agent",
        "Own security review: threat models, permission boundaries, secret handling, OAuth isolation, sandbox correctness, dependency and license review, and regression tests for unsafe behavior. Report defects instead of weakening controls.",
        PROJECT_WRITE_SCOPE,
    ),
    "ai_release_agent": SpecialistDefinition(
        "ai_release_agent", "AI Release Agent",
        "Own native release preparation: version metadata, installers, manifests, checksums, license compliance evidence, release notes, publication gates, and rollback plans. Never bypass required source-availability or signing gates.",
        PROJECT_WRITE_SCOPE,
    ),
    "ai_support_agent": SpecialistDefinition(
        "ai_support_agent", "AI Support Agent",
        "Own user-facing documentation, download guidance, troubleshooting, status reports, and support-facing honesty about supported platforms and known limitations. Keep the public site informational and separate from the native Studio.",
        PROJECT_WRITE_SCOPE,
    ),
}

# Compatibility for persisted missions created before the current role set was
# named explicitly. New plans and CLI selections use the registered IDs.
LEGACY_SPECIALIST_ALIASES = {
    "core": "research",
    "design": "studio",
    "repair": "code",
    "integration": "server",
    "general": "code",
    "gaming": "game",
}

GAME_CHECK_ROLES = ("game", "ai_games_agent")
FINAL_VERIFICATION_MARKER = "STREAMIOV_FINAL_VERIFICATION"
FINAL_VERIFICATION_PREFIX = FINAL_VERIFICATION_MARKER + ":"
VERIFICATION_REPAIR_MARKER = "STREAMIOV_VERIFICATION_REPAIR"
FINAL_VERIFICATION_ROLES = ("testing", "ai_testing_agent")
FINAL_VERIFICATION_ROLE = "ai_testing_agent"
VERIFICATION_REPAIR_ROLES = ("repair", "ai_repair_agent")
VERIFICATION_REPAIR_ROLE = "ai_repair_agent"


def specialist_names() -> tuple[str, ...]:
    return tuple(SPECIALISTS)


def get_specialist(name: str) -> SpecialistDefinition:
    if not isinstance(name, str):
        raise ValueError("Specialist name must be text.")
    canonical = LEGACY_SPECIALIST_ALIASES.get(name, name)
    if canonical not in SPECIALISTS:
        raise ValueError(f"Unknown specialist '{name}'. Choose one of: {', '.join(SPECIALISTS)}")
    return SPECIALISTS[canonical]


def task_prompt_for_specialist(name: str, prompt: str) -> str:
    """Return a task prompt with any role-required reserved marker."""
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("Task prompt must be non-empty text.")
    canonical = get_specialist(name).key
    prepared = prompt.strip()
    verification_role = canonical in FINAL_VERIFICATION_ROLES or name in FINAL_VERIFICATION_ROLES
    repair_role = canonical in VERIFICATION_REPAIR_ROLES or name in VERIFICATION_REPAIR_ROLES
    if verification_role and not prepared.startswith(FINAL_VERIFICATION_PREFIX):
        prepared = FINAL_VERIFICATION_PREFIX + " " + prepared
    if repair_role and not prepared.startswith(VERIFICATION_REPAIR_MARKER):
        prepared = VERIFICATION_REPAIR_MARKER + ": " + prepared
    return prepared


def build_specialist_system_prompt(name: str, base_prompt: str) -> str:
    specialist = get_specialist(name)
    scope = ", ".join(specialist.writable_prefixes)
    return (
        f"{base_prompt.strip()}\n\n"
        f"SPECIALIST ROLE: {specialist.title} ({specialist.key})\n"
        f"MISSION: {specialist.mission}\n"
        f"WRITE SCOPE: You may create and edit project files across all modules: {scope}. "
        "The runtime enforces project-wide access independently and blocks protected control-plane paths. "
        "Protected OAuth, credential, secret, provider, core AI control-plane, deployment-config, workflow, runner-permission, and access-control paths remain inaccessible. "
        "Specialist roles define separate product ownership and expertise, not module-level write barriers. "
        "Do not attempt to bypass or modify the permission enforcement."
    )
