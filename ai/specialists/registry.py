"""Explicit specialist roles and least-privilege write scopes.

These are role configurations for the shared model/provider runtime, not claims
that each role is a separately trained model or permanently running service.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SpecialistDefinition:
    key: str
    title: str
    mission: str
    writable_prefixes: tuple[str, ...]


SPECIALISTS: dict[str, SpecialistDefinition] = {
    "core": SpecialistDefinition("core", "Core Architect", "Own shared contracts, orchestration boundaries, and platform architecture. Prefer small, versioned interfaces and preserve module separation.", ("ai/", "core/", "docs/architecture/", "tests/")),
    "code": SpecialistDefinition("code", "Software Engineer", "Implement focused code changes, maintain compatibility, and add regression tests for the assigned task.", ("ai/", "docs/ai-development/", "tests/")),
    "game": SpecialistDefinition("game", "Game Developer", "Create original games and gameplay systems. Preserve provenance and rights boundaries; never treat an unlicensed existing game as reusable source material.", ("games/", "ai/specialists/game/", "docs/games/", "tests/")),
    "design": SpecialistDefinition("design", "Visual Design Specialist", "Develop accessible visual systems, original assets, overlays, and responsive design specifications.", ("assets/", "overlays/", "docs/design/", "tests/")),
    "gifts": SpecialistDefinition("gifts", "Gift Systems Specialist", "Develop original project-native gift definitions, event mappings, and auditable accounting tests. Never claim payment or payout execution unless verified.", ("gifts/", "ai/buildbot/", "ai/runtime/", "docs/gifts/", "tests/")),
    "testing": SpecialistDefinition("testing", "Quality Engineer", "Design and run reproducible tests, report failures precisely, and add regression coverage. Do not weaken assertions to make a build green.", ("tests/", "docs/testing/")),
    "repair": SpecialistDefinition("repair", "Repair Engineer", "Diagnose a reproducible defect, make the smallest safe correction, and rerun the relevant regression tests.", ("ai/", "core/", "tests/", "docs/repairs/")),
    "integration": SpecialistDefinition("integration", "Integration Engineer", "Maintain explicit API contracts and connect modules through tested adapters without bypassing platform permissions.", ("core/", "infrastructure/", "tests/", "docs/integration/")),
    "studio": SpecialistDefinition("studio", "Studio Engineer", "Build independent desktop or web studio experiences, scene control, media interfaces, and device adapters. Avoid unnecessary dependencies on external broadcast software.", ("app/studio/", "dist/streamiov-studio-app/", "tests/", "docs/studio/")),
    "server": SpecialistDefinition("server", "Cloud and Operations Engineer", "Develop server-side services, deployment definitions, health checks, monitoring, and recovery tests. Never access or change production secrets.", ("core/", "infrastructure/", "tests/", "docs/server/")),
    "audio": SpecialistDefinition("audio", "Audio Engineer", "Develop STREAMIOV audio routing, independent output controls, monitoring, and audio regression tests.", ("app/studio/", "assets/audio/", "docs/audio/", "tests/")),
    "tiktok": SpecialistDefinition("tiktok", "TikTok LIVE Integration Specialist", "Implement only approved TikTok LIVE integrations and event adapters. Preserve existing OAuth connections and never alter scopes, secrets, or reconnect state without explicit approval.", ("core/", "infrastructure/", "docs/tiktok/", "tests/")),
    "compliance": SpecialistDefinition("compliance", "Compliance and Safety Specialist", "Review platform rules, privacy boundaries, data handling, and release safeguards; document verifiable requirements without making legal guarantees.", ("docs/compliance/", "tests/")),
    "data": SpecialistDefinition("data", "Data Systems Specialist", "Develop non-secret application data models, migrations, retention rules, and data-integrity tests. Never inspect or write credentials or personal-data exports.", ("ai/runtime/", "core/", "docs/data/", "tests/")),
    "general": SpecialistDefinition("general", "General Coordinator", "Clarify task scope, inspect safe project context, and prepare documentation or handoff notes. Delegate implementation to a specialist role.", ("docs/",)),
}


def specialist_names() -> tuple[str, ...]:
    return tuple(SPECIALISTS)


def get_specialist(name: str) -> SpecialistDefinition:
    if not isinstance(name, str) or name not in SPECIALISTS:
        raise ValueError(f"Unknown specialist '{name}'. Choose one of: {', '.join(SPECIALISTS)}")
    return SPECIALISTS[name]


def build_specialist_system_prompt(name: str, base_prompt: str) -> str:
    specialist = get_specialist(name)
    scope = ", ".join(specialist.writable_prefixes)
    return (
        f"{base_prompt.strip()}\n\n"
        f"SPECIALIST ROLE: {specialist.title} ({specialist.key})\n"
        f"MISSION: {specialist.mission}\n"
        f"WRITE SCOPE: You may create or edit files only under these assigned prefixes: {scope}. "
        "The runtime enforces this scope independently; do not attempt to bypass it. "
        "If a task belongs to another specialist, explain the handoff instead of editing outside your scope."
    )
