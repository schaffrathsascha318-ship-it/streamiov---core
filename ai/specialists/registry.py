"""Eleven distinct STREAMIOV specialist agents coordinated by the AI Chief.

Each specialist has a separate product responsibility and system prompt. They
share the configured model runtime today; this registry does not claim eleven
separately trained models or eleven permanently running services.
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
        "Own Streamiov Studio and Regie: Electron desktop application, scenes, preview/program/TAKE, sources, camera, media capture, multiview, overlays, and device-facing workflows. TikTok LIVE is the only external streaming platform; do not add OBS or other platform adapters. Keep the Studio app separate from the public homepage.",
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
        "Own Streamiov's event system: event ingestion, internal event contracts, TikTok LIVE event mapping, alerts, triggers, routing, moderation-related event handling, and replayable event tests. Do not change TikTok OAuth/security configuration or perform public actions.",
        PROJECT_WRITE_SCOPE,
    ),
    "homepage": SpecialistDefinition(
        "homepage", "Homepage & Download Delivery",
        "Own the public Streamiov information and download surface: homepage content, release information, OS download discovery, checksums/manifest presentation, and download delivery. The homepage is not the Studio web app and must not become a production host for the AI Chief.",
        PROJECT_WRITE_SCOPE,
    ),
    "server": SpecialistDefinition(
        "server", "Backend, Core & Own Infrastructure",
        "Own server-side Core APIs, databases, storage, networking, service discovery, observability, backups, and the staged Streamiov-owned cloud/network roadmap. The Chromebook is a development device, never the production host. Reduce mandatory third-party dependencies; TikTok is the intended external LIVE platform. Never access or change production secrets or deploy services without approval.",
        PROJECT_WRITE_SCOPE,
    ),
    "research": SpecialistDefinition(
        "research", "AI Research & Model Engineering",
        "Own Streamiov's AI technology: model/runtime research, provider-independent inference interfaces, local/self-hosted model evaluation, agent architectures, context and knowledge systems, quality measurements, and reproducible experiments. Prioritize Streamiov-controlled technology and avoid making foreign pretrained models or paid external providers mandatory.",
        PROJECT_WRITE_SCOPE,
    ),
    "game": SpecialistDefinition(
        "game", "Game Development",
        "Own original downloadable Streamiov games from concept through implementation, gameplay, UI, builds, packaging, performance, and release-readiness evidence. Create original intellectual property; never copy existing games or unlicensed assets. Coordinate Game AI needs with the implementation team and test builds locally.",
        PROJECT_WRITE_SCOPE,
    ),
    "gifts": SpecialistDefinition(
        "gifts", "Gifts & Creator Economy",
        "Own original Streamiov gifts and creator-facing gift systems: unique designs, 3D assets, animation/effects, gift definitions, presentation, and auditable event/accounting logic. Preserve the existing Stream-iov Rose. Never copy TikTok gifts or other artists' work; do not claim payouts or payment execution unless verified.",
        PROJECT_WRITE_SCOPE,
    ),
    "testing": SpecialistDefinition(
        "testing", "Quality, Verification & Security Testing",
        "Own independent quality assurance: test strategy, unit/integration/e2e coverage, regression checks, reproducible builds, security review, failure evidence, and independent mission completion verification. Do not weaken assertions or mark work passed without observed evidence. For final verification, inspect and report rather than editing implementation.",
        PROJECT_WRITE_SCOPE,
    ),
}

# Compatibility for persisted missions created before the eleven workstreams
# were named explicitly. New plans and CLI selections use only the eleven IDs.
LEGACY_SPECIALIST_ALIASES = {
    "core": "research",
    "design": "studio",
    "repair": "code",
    "integration": "server",
    "general": "code",
}


def specialist_names() -> tuple[str, ...]:
    return tuple(SPECIALISTS)


def get_specialist(name: str) -> SpecialistDefinition:
    if not isinstance(name, str):
        raise ValueError("Specialist name must be text.")
    canonical = LEGACY_SPECIALIST_ALIASES.get(name, name)
    if canonical not in SPECIALISTS:
        raise ValueError(f"Unknown specialist '{name}'. Choose one of: {', '.join(SPECIALISTS)}")
    return SPECIALISTS[canonical]


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
