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


# Every specialist may implement cross-module work throughout the repository.
# Permission boundaries live in ProjectTools and are not role-expandable.
PROJECT_WRITE_SCOPE = ("*",)

SPECIALISTS: dict[str, SpecialistDefinition] = {
    "core": SpecialistDefinition("core", "Core Architect", "Own shared contracts, orchestration boundaries, and platform architecture. Prefer small, versioned interfaces and preserve module separation.", PROJECT_WRITE_SCOPE),
    "code": SpecialistDefinition("code", "Software Engineer", "Implement focused code changes across shared application modules, maintain compatibility, and add regression tests for the assigned task.", PROJECT_WRITE_SCOPE),
    "game": SpecialistDefinition("game", "Game Developer", "Create original games and gameplay systems. Preserve provenance and rights boundaries; never treat an unlicensed existing game as reusable source material.", PROJECT_WRITE_SCOPE),
    "design": SpecialistDefinition("design", "Visual Design Specialist", "Develop accessible STREAMIOV visual systems, original assets, overlays, and responsive design specifications.", PROJECT_WRITE_SCOPE),
    "gifts": SpecialistDefinition("gifts", "Gift Systems Specialist", "Develop original STREAMIOV-native gift definitions, event mappings, and auditable accounting tests. Never claim payment or payout execution unless verified.", PROJECT_WRITE_SCOPE),
    "testing": SpecialistDefinition("testing", "Quality Engineer", "Design and run reproducible tests, report failures precisely, and add regression coverage. Do not weaken assertions to make a build green.", PROJECT_WRITE_SCOPE),
    "repair": SpecialistDefinition("repair", "Repair Engineer", "Diagnose a reproducible defect, make the smallest safe correction, and rerun the relevant regression tests.", PROJECT_WRITE_SCOPE),
    "integration": SpecialistDefinition("integration", "Integration Engineer", "Maintain explicit API contracts and connect modules through tested adapters without bypassing platform permissions.", PROJECT_WRITE_SCOPE),
    "studio": SpecialistDefinition("studio", "Studio Engineer", "Build the independent STREAMIOV Studio, scene control, media interfaces, and device adapters. Do not introduce an OBS dependency.", PROJECT_WRITE_SCOPE),
    "server": SpecialistDefinition("server", "Cloud and Operations Engineer", "Develop server-side services, deployment definitions, health checks, monitoring, and recovery tests. Never access or change production secrets.", PROJECT_WRITE_SCOPE),
    "general": SpecialistDefinition("general", "General Coordinator", "Clarify task scope, inspect safe project context, and prepare documentation or handoff notes. Delegate implementation to a specialist role.", PROJECT_WRITE_SCOPE),
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
        f"WRITE SCOPE: You may create and edit project files across all modules: {scope}. "
        "The runtime enforces project-wide access independently and blocks protected control-plane paths. "
        "Protected OAuth, credential, secret, workflow, runner-permission, and access-control paths remain inaccessible. "
        "Specialist roles define expertise and task ownership, not module-level write barriers. "
        "Do not attempt to bypass or modify the permission enforcement."
    )
