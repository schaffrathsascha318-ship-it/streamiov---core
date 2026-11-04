#!/usr/bin/env python3
"""Collect an honest hardware report for the STREAMIOV acceptance checklist.

Run this on every test device and attach the output to
docs/operations/external-verification.md. It records OS, CPU, memory, tool
versions, FFmpeg capabilities, the checked-out commit and the SHA-256 of the
installers you tested. It reads no credentials and makes no network calls.

Examples:
    python3 scripts/collect-hardware-report.py
    python3 scripts/collect-hardware-report.py --markdown
    python3 scripts/collect-hardware-report.py ~/Downloads/Streamiov.Studio.Setup.1.0.1-x64.exe
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(command: list[str], timeout: int = 20) -> str | None:
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return (result.stdout or result.stderr).strip()


def cpu_model() -> str:
    if Path("/proc/cpuinfo").is_file():
        for line in Path("/proc/cpuinfo").read_text(encoding="utf-8", errors="replace").splitlines():
            if line.lower().startswith("model name"):
                return line.split(":", 1)[1].strip()
    return platform.processor() or platform.machine()


def memory_mib() -> int | None:
    if Path("/proc/meminfo").is_file():
        for line in Path("/proc/meminfo").read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("MemTotal:"):
                return round(int(line.split()[1]) / 1024)
    return None


def ffmpeg_report() -> dict[str, object]:
    if not shutil.which("ffmpeg"):
        return {"available": False, "libx264": False, "aac": False, "rtmp": False}
    encoders = run(["ffmpeg", "-hide_banner", "-encoders"]) or ""
    protocols = run(["ffmpeg", "-hide_banner", "-protocols"]) or ""
    version = run(["ffmpeg", "-hide_banner", "-version"]) or ""
    return {
        "available": True,
        "version": version.splitlines()[0] if version else None,
        "libx264": "libx264" in encoders,
        "aac": " aac " in f" {encoders} ",
        "rtmp": any(line.strip() == "rtmp" for line in protocols.splitlines())
        or "rtmp" in protocols.split(),
    }


def file_entry(path: Path) -> dict[str, object]:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return {"file": str(path), "bytes": path.stat().st_size, "sha256": digest.hexdigest()}


def collect(files: list[Path]) -> dict[str, object]:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "commit": run(["git", "rev-parse", "--short", "HEAD"], timeout=10),
        "os": {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "platform": platform.platform(),
            "distribution": next(
                (line.split("=", 1)[1].strip().strip('"') for line in
                 Path("/etc/os-release").read_text(encoding="utf-8", errors="replace").splitlines()
                 if line.startswith("PRETTY_NAME=")), None,
            ) if Path("/etc/os-release").is_file() else None,
        },
        "hardware": {
            "machine": platform.machine(),
            "processor": cpu_model(),
            "cpu_count": os.cpu_count(),
            "memory_mib": memory_mib(),
        },
        "tools": {
            "python": platform.python_version(),
            "node": run(["node", "--version"], timeout=10),
            "ffmpeg": ffmpeg_report(),
        },
        "files": [file_entry(path) for path in files],
        "note": "Keine Zugangsdaten, Tokens oder Stream-Keys in diesen Bericht aufnehmen.",
    }


def as_markdown(report: dict[str, object]) -> str:
    os_info = report["os"]
    hardware = report["hardware"]
    tools = report["tools"]
    ffmpeg = tools["ffmpeg"]
    lines = [
        "# STREAMIOV Hardware-Bericht",
        "",
        f"- Zeitpunkt (UTC): {report['generated_at']}",
        f"- Commit: {report['commit'] or 'unbekannt'}",
        f"- System: {os_info['system']} {os_info['release']} ({os_info['distribution'] or os_info['version']})",
        f"- Plattform: {os_info['platform']}",
        f"- CPU: {hardware['processor']} ({hardware['cpu_count']} Threads)",
        f"- RAM: {hardware['memory_mib']} MiB",
        f"- Python: {tools['python']} · Node: {tools['node'] or 'fehlt'}",
        f"- FFmpeg: {ffmpeg.get('version') or 'fehlt'} · libx264: {ffmpeg['libx264']} · AAC: {ffmpeg['aac']} · RTMP: {ffmpeg['rtmp']}",
        "",
        "| Datei | Bytes | SHA-256 |",
        "|---|---:|---|",
    ]
    for item in report["files"]:
        lines.append(f"| `{item['file']}` | {item['bytes']} | `{item['sha256']}` |")
    lines.append("")
    lines.append(report["note"])
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("files", nargs="*", type=Path, help="Getestete Installer/Archive")
    parser.add_argument("--markdown", action="store_true", help="Statt JSON einen Markdown-Bericht ausgeben")
    parser.add_argument("--out", type=Path, help="Bericht zusätzlich in diese Datei schreiben")
    args = parser.parse_args()

    missing = [str(path) for path in args.files if not path.is_file()]
    if missing:
        print(f"FEHLER: Datei fehlt: {', '.join(missing)}", file=sys.stderr)
        raise SystemExit(2)

    report = collect(args.files)
    output = as_markdown(report) if args.markdown else json.dumps(report, indent=2, ensure_ascii=False)
    print(output)
    if args.out:
        args.out.write_text(output + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
