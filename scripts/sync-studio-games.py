"""Copy registered independent STREAMIOV games into the Electron app package."""
from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "games"
APP = ROOT / "dist" / "streamiov-studio-app"
TARGET = APP / "games"


def main() -> int:
    registry_path = SOURCE / "registry.json"
    if not registry_path.is_file() or registry_path.is_symlink():
        raise SystemExit("Game registry is missing or unsafe.")

    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    if registry.get("schemaVersion") != 1 or not isinstance(registry.get("games"), list):
        raise SystemExit("Unsupported game registry schema.")

    APP.mkdir(parents=True, exist_ok=True)
    if TARGET.is_symlink():
        raise SystemExit(f"Refusing to replace symlink: {TARGET}")

    temporary = Path(tempfile.mkdtemp(prefix=".games-sync-", dir=APP))
    staged = temporary / "games"
    staged.mkdir()
    try:
        shutil.copy2(registry_path, staged / "registry.json")
        readme = SOURCE / "README.md"
        if readme.is_file() and not readme.is_symlink():
            shutil.copy2(readme, staged / "README.md")

        seen: set[str] = set()
        for game in registry["games"]:
            game_id = game.get("id")
            if not isinstance(game_id, str) or not game_id.replace("-", "").isalnum() or game_id in seen:
                raise SystemExit("Invalid or duplicate game ID in registry.")
            seen.add(game_id)

            if game.get("path") != f"games/{game_id}":
                raise SystemExit(f"Unexpected game path for {game_id}.")
            source_dir = SOURCE / game_id
            manifest_path = source_dir / "game.json"
            if not source_dir.is_dir() or source_dir.is_symlink() or not manifest_path.is_file() or manifest_path.is_symlink():
                raise SystemExit(f"Game package is missing or unsafe: {game_id}")

            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if manifest.get("id") != game_id:
                raise SystemExit(f"Manifest ID mismatch for {game_id}.")
            entry = manifest.get("entry")
            if not isinstance(entry, str) or Path(entry).is_absolute() or ".." in Path(entry).parts:
                raise SystemExit(f"Unsafe game entry point for {game_id}.")
            if not (source_dir / entry).is_file():
                raise SystemExit(f"Game entry point missing for {game_id}.")

            destination = staged / game_id
            shutil.copytree(
                source_dir,
                destination,
                ignore=shutil.ignore_patterns("tests", "__pycache__", "*.pyc", ".DS_Store"),
                symlinks=False,
            )

        backup = APP / (".games-old-" + str(os.getpid()))
        if backup.exists():
            shutil.rmtree(backup)
        if TARGET.exists():
            os.replace(TARGET, backup)
        try:
            os.replace(staged, TARGET)
        except Exception:
            if backup.exists() and not TARGET.exists():
                os.replace(backup, TARGET)
            raise
        if backup.exists():
            shutil.rmtree(backup)
        print(f"Prepared {len(seen)} independent game packages in {TARGET.relative_to(ROOT)}")
        return 0
    finally:
        if temporary.exists():
            shutil.rmtree(temporary, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
