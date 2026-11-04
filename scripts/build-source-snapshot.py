#!/usr/bin/env python3
"""Build the public source snapshot and split it into fixed-size parts.

The snapshot is source code, not an installer. It deliberately excludes local
credentials, production databases, generated installers, caches, backups, and
binary download artifacts. It also excludes the generated download metadata
(part files, checksums, combine.js and the download page that embeds their
sizes/hashes), because those values depend on the archive itself and would
otherwise make every rebuild differ.

Entries are written with a fixed timestamp, so the same commit always produces
the same archive bytes, part layout and checksums on any machine.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
DOWNLOADS = ROOT / "dist/streamiov-homepage-worker/public/downloads"
ARCHIVE_NAME = "streamiov-studio-source-20261103.zip"
PART_COUNT = 7

EXCLUDED_PARTS = {
    ".git",
    "node_modules",
    "__pycache__",
    ".wrangler",
    "release",
    "secrets",
    "storage",
    "logs",
    ".testdir",
    "backups",
}
EXCLUDED_PREFIXES = (
    # Generated download metadata: the part files/checksums plus the page and
    # combiner that embed the resulting sizes and hashes.
    "dist/streamiov-homepage-worker/public/download/",
    "dist/streamiov-homepage-worker/public/downloads/",
    "dist/streamiov-homepage-worker/public/promo/media/",
    "dist/streamiov-studio-app/release/",
    "dist/streamiov-studio-app/backup-",
    "data/db/",
)
EXCLUDED_SUFFIXES = (
    ".pyc",
    ".log",
    ".pid",
    ".sqlite",
    ".sqlite3",
    ".zip",
    ".tar",
    ".tar.gz",
    ".bak",
    ".save",
    ".before",
)
EXCLUDED_MARKERS = ("-backup-", ".bak-", ".before-", ".vor-")


def is_excluded(relative: str) -> bool:
    path = PurePosixPath(relative)
    if any(part in EXCLUDED_PARTS for part in path.parts):
        return True
    if any(relative.startswith(prefix) for prefix in EXCLUDED_PREFIXES):
        return True
    if relative.endswith(EXCLUDED_SUFFIXES):
        return True
    if any(marker in relative for marker in EXCLUDED_MARKERS):
        return True
    name = path.name
    if name.startswith(".env") and not name.endswith(".example"):
        return True
    if name.startswith("backup-") or name.startswith("backups-"):
        return True
    return False


def source_files() -> list[str]:
    commands = [
        ["git", "ls-files", "-z"],
        ["git", "ls-files", "-z", "--others", "--exclude-standard"],
    ]
    names: set[str] = set()
    for command in commands:
        output = subprocess.run(command, cwd=ROOT, check=True, capture_output=True).stdout
        names.update(item for item in output.decode("utf-8").split("\0") if item)
    return sorted(name for name in names if not is_excluded(name))


ZIP_TIMESTAMP = (2026, 11, 3, 0, 0, 0)


def build_archive(files: list[str]) -> Path:
    target = ROOT / "dist" / ARCHIVE_NAME
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for relative in files:
            source = ROOT / relative
            if not source.is_file():
                continue
            info = zipfile.ZipInfo(relative, date_time=ZIP_TIMESTAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = (0o100644 & 0xFFFF) << 16
            archive.writestr(info, source.read_bytes(), compresslevel=9)
    return target


def split_archive(archive: Path) -> list[Path]:
    data = archive.read_bytes()
    base, remainder = divmod(len(data), PART_COUNT)
    DOWNLOADS.mkdir(parents=True, exist_ok=True)
    for old in DOWNLOADS.glob("streamiov-studio-part-*.bin"):
        old.unlink()
    parts: list[Path] = []
    offset = 0
    for index in range(PART_COUNT):
        size = base + (1 if index < remainder else 0)
        part = DOWNLOADS / f"streamiov-studio-part-{index:02d}.bin"
        part.write_bytes(data[offset:offset + size])
        parts.append(part)
        offset += size
    return parts


def part_metadata(parts: list[Path]) -> list[dict[str, object]]:
    return [
        {
            "name": part.name,
            "bytes": part.stat().st_size,
            "sha256": hashlib.sha256(part.read_bytes()).hexdigest(),
        }
        for part in parts
    ]


def update_download_combiner(part_data: list[dict[str, object]], digest: str) -> None:
    target = ROOT / "dist/streamiov-homepage-worker/public/download/combine.js"
    script = target.read_text(encoding="utf-8")
    entries = ",\n".join(
        '    {\n'
        f'      name: "{item["name"]}",\n'
        f'      size: {item["bytes"]},\n'
        f'      sha256: "{item["sha256"]}"\n'
        '    }'
        for item in part_data
    )
    parts_block = f"  const parts = [\n{entries}\n  ];"
    script, replacements = re.subn(
        r"  const parts = \[.*?\n  \];",
        parts_block,
        script,
        count=1,
        flags=re.DOTALL,
    )
    if replacements != 1:
        raise SystemExit("combine.js: parts block not found")
    script, replacements = re.subn(
        r'const expectedArchiveSha256 =\n    "[0-9a-f]{64}";',
        f'const expectedArchiveSha256 =\n    "{digest}";',
        script,
        count=1,
    )
    if replacements != 1:
        raise SystemExit("combine.js: archive hash not found")
    target.write_text(script, encoding="utf-8")


def update_download_page(part_data: list[dict[str, object]], digest: str) -> None:
    target = ROOT / "dist/streamiov-homepage-worker/public/download/index.html"
    html = target.read_text(encoding="utf-8")
    total = sum(int(item["bytes"]) for item in part_data)
    formatted_total = f"{total:,}".replace(",", ".")
    html, replacements = re.subn(
        r"Gesamtgröße: [\d.]+ Bytes",
        f"Gesamtgröße: {formatted_total} Bytes",
        html,
        count=1,
    )
    if replacements != 1:
        raise SystemExit("download page: total size not found")
    html, replacements = re.subn(
        r"(SHA-256 des zusammengefügten ZIPs: <code>)[0-9a-f]{64}(</code>)",
        rf"\g<1>{digest}\g<2>",
        html,
        count=1,
    )
    if replacements != 1:
        raise SystemExit("download page: archive hash not found")
    target.write_text(html, encoding="utf-8")


def write_checksums(archive: Path, parts: list[Path]) -> dict[str, object]:
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    part_data = part_metadata(parts)
    lines = [
        "# StreamioV Studio source snapshot 2026-11-03",
        "# Verify a part with: sha256sum -c SHA256SUMS.txt",
        f"# Verify the assembled archive with: sha256sum {ARCHIVE_NAME}",
        f"# assembled archive: {digest}  {ARCHIVE_NAME}",
    ]
    for item in part_data:
        lines.append(f'{item["sha256"]}  {item["name"]}')
    (DOWNLOADS / "SHA256SUMS.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    archive.unlink()
    update_download_combiner(part_data, digest)
    update_download_page(part_data, digest)
    return {
        "archive": ARCHIVE_NAME,
        "bytes": sum(int(item["bytes"]) for item in part_data),
        "sha256": digest,
        "parts": part_data,
    }


def main() -> None:
    files = source_files()
    archive = build_archive(files)
    parts = split_archive(archive)
    print(json.dumps(write_checksums(archive, parts), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
