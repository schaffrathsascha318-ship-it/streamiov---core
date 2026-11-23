"""Structured foundation for the StreamioV AI Game Studio.

This module turns a complete, original game brief into a durable project
workspace. It deliberately creates a DESIGN workspace, never a playable build
or release claim. Implementation and gameplay verification remain separate.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


REQUIRED_TEXT = (
    "vision", "core_gameplay", "progression", "art_direction",
    "audio_direction", "accessibility", "test_plan",
)
SAFE_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class GameBriefError(ValueError):
    """Raised when a game brief is incomplete or unsafe."""


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise GameBriefError(f"{field} must be non-empty text.")
    return value.strip()


def _string_list(value: Any, field: str, minimum: int = 1) -> list[str]:
    if not isinstance(value, list) or len(value) < minimum:
        raise GameBriefError(f"{field} must contain at least {minimum} entries.")
    result = [_text(item, f"{field}[{index}]") for index, item in enumerate(value)]
    normalized = [item.casefold() for item in result]
    if len(normalized) != len(set(normalized)):
        raise GameBriefError(f"{field} must not contain duplicates.")
    return result


def validate_game_brief(brief: dict[str, Any]) -> dict[str, Any]:
    """Validate a substantial original-game design brief and return audit data."""
    if not isinstance(brief, dict):
        raise GameBriefError("Game brief must be a JSON object.")
    game_id = brief.get("id")
    if not isinstance(game_id, str) or not SAFE_ID.fullmatch(game_id):
        raise GameBriefError("id must be a lowercase kebab-case project identifier.")
    title = _text(brief.get("title"), "title")
    genre = _text(brief.get("genre"), "genre")
    for field in REQUIRED_TEXT:
        _text(brief.get(field), field)

    platforms = _string_list(brief.get("target_platforms"), "target_platforms")
    mechanics = _string_list(brief.get("signature_mechanics"), "signature_mechanics", 2)
    core_loop = _string_list(brief.get("core_loop"), "core_loop", 3)
    level_plan = _string_list(brief.get("level_plan"), "level_plan", 3)
    controls = brief.get("controls")
    if not isinstance(controls, dict) or not controls:
        raise GameBriefError("controls must map supported input types to clear instructions.")
    for input_type, instruction in controls.items():
        _text(input_type, "controls input type")
        _text(instruction, f"controls.{input_type}")

    rights = brief.get("rights")
    if not isinstance(rights, dict):
        raise GameBriefError("rights must be an object.")
    if rights.get("original_concept") is not True:
        raise GameBriefError("Only explicitly original concepts enter this clean-room builder.")
    third_party = rights.get("third_party_components", [])
    if not isinstance(third_party, list):
        raise GameBriefError("rights.third_party_components must be an array.")
    for index, component in enumerate(third_party):
        if not isinstance(component, dict):
            raise GameBriefError(f"third_party_components[{index}] must be an object.")
        _text(component.get("name"), f"third_party_components[{index}].name")
        _text(component.get("origin"), f"third_party_components[{index}].origin")
        _text(component.get("license"), f"third_party_components[{index}].license")

    return {
        "valid": True,
        "project_id": game_id,
        "title": title,
        "genre": genre,
        "target_platforms": platforms,
        "signature_mechanics": mechanics,
        "core_loop_steps": len(core_loop),
        "planned_levels_or_challenges": len(level_plan),
        "third_party_components": len(third_party),
        "playability_verified": False,
        "build_verified": False,
        "gameplay_verified": False,
        "release_ready": False,
        "status": "DESIGN_BRIEF_VALIDATED",
    }


def create_design_workspace(brief: dict[str, Any], repository_root: str | Path) -> dict[str, Any]:
    """Create a new, non-overwriting design workspace under games/ai_created."""
    audit = validate_game_brief(brief)
    root = Path(repository_root).resolve()
    games_root = root / "games" / "ai_created"
    games_root.mkdir(parents=True, exist_ok=True)
    if games_root.is_symlink():
        raise GameBriefError("AI game workspace root must not be a symlink.")
    destination = games_root / audit["project_id"]
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(f"Game workspace already exists: {audit['project_id']}")
    destination.mkdir()
    try:
        (destination / "design-brief.json").write_text(
            json.dumps(brief, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (destination / "builder-audit.json").write_text(
            json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (destination / "README.md").write_text(
            f"# {audit['title']}\n\n"
            f"**Status:** DESIGN_BRIEF_VALIDATED — not a playable game or release.\n\n"
            f"**Genre:** {audit['genre']}\n\n"
            "## Production gate\n\n"
            "- [ ] Original gameplay implemented; no placeholder loop.\n"
            "- [ ] Distinctive art, animation, UI and audio created and provenance recorded.\n"
            "- [ ] Controls, progression, levels and accessibility implemented.\n"
            "- [ ] Automated unit, integration and compatibility tests pass.\n"
            "- [ ] Real gameplay completed and verified on each claimed device family.\n"
            "- [ ] Rights, licences, credits and asset provenance reviewed.\n"
            "- [ ] Versioned platform packages and checksums generated.\n"
            "- [ ] Independent release review passed.\n",
            encoding="utf-8",
        )
    except Exception:
        for child in destination.iterdir():
            child.unlink()
        destination.rmdir()
        raise
    return {**audit, "workspace": destination.relative_to(root).as_posix()}


def main() -> int:
    parser = argparse.ArgumentParser(description="StreamioV AI Game Studio design workspace builder")
    parser.add_argument("brief", help="Path to a UTF-8 JSON game design brief")
    parser.add_argument("--repository-root", default=".")
    args = parser.parse_args()
    try:
        brief = json.loads(Path(args.brief).read_text(encoding="utf-8"))
        result = create_design_workspace(brief, args.repository_root)
    except (OSError, json.JSONDecodeError, GameBriefError, FileExistsError) as exc:
        parser.exit(2, f"streamiov-game-studio: {exc}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
