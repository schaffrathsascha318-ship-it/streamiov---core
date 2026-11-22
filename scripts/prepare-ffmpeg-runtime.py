#!/usr/bin/env python3
"""Fetch and validate a pinned FFmpeg-Builds GPL runtime for one target architecture."""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import shutil
import struct
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile

UPSTREAM = "https://github.com/FFmpeg-Builds/FFmpeg-Builds"
FFMPEG_SOURCE = "https://github.com/FFmpeg/FFmpeg"


def download(url: str, destination: pathlib.Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "Streamiov-Studio-build"})
    with urllib.request.urlopen(request, timeout=90) as response, destination.open("wb") as output:
        shutil.copyfileobj(response, output, length=1024 * 1024)


def sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def extract_binary(archive: pathlib.Path, is_windows: bool, destination: pathlib.Path) -> None:
    expected = "ffmpeg.exe" if is_windows else "ffmpeg"
    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as bundle:
            matches = [item for item in bundle.infolist()
                       if pathlib.PurePosixPath(item.filename).name == expected
                       and "bin" in pathlib.PurePosixPath(item.filename).parts
                       and not item.is_dir()]
            if len(matches) != 1:
                raise RuntimeError(f"Expected exactly one bin/{expected} in ZIP; found {len(matches)}")
            with bundle.open(matches[0]) as source, destination.open("wb") as output:
                shutil.copyfileobj(source, output, length=1024 * 1024)
        return
    with tarfile.open(archive, "r:xz") as bundle:
        matches = [item for item in bundle.getmembers()
                   if pathlib.PurePosixPath(item.name).name == expected
                   and "bin" in pathlib.PurePosixPath(item.name).parts
                   and item.isfile()]
        if len(matches) != 1:
            raise RuntimeError(f"Expected exactly one bin/{expected} in tarball; found {len(matches)}")
        source = bundle.extractfile(matches[0])
        if source is None:
            raise RuntimeError("Could not read FFmpeg executable from archive")
        with source, destination.open("wb") as output:
            shutil.copyfileobj(source, output, length=1024 * 1024)


def pe_machine(path: pathlib.Path) -> int:
    with path.open("rb") as stream:
        if stream.read(2) != b"MZ":
            raise RuntimeError("Windows FFmpeg binary is not a PE executable")
        stream.seek(0x3C)
        offset = struct.unpack("<I", stream.read(4))[0]
        stream.seek(offset)
        if stream.read(4) != b"PE\\0\\0":
            raise RuntimeError("Windows FFmpeg binary has an invalid PE signature")
        return struct.unpack("<H", stream.read(2))[0]


def run(binary: pathlib.Path, *args: str) -> str:
    completed = subprocess.run([str(binary), *args], check=True, capture_output=True,
                               text=True, timeout=45)
    return completed.stdout + completed.stderr


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--asset", required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--build-scripts-commit", required=True)
    parser.add_argument("--target", choices=("win64", "winarm64", "linux64", "linuxarm64"), required=True)
    args = parser.parse_args()

    is_windows = args.target.startswith("win")
    executable_name = "ffmpeg.exe" if is_windows else "ffmpeg"
    app_root = pathlib.Path(__file__).resolve().parents[1] / "dist" / "streamiov-studio-app"
    runtime_dir = app_root / "ffmpeg"
    binary_dir = runtime_dir / "bin"
    binary_dir.mkdir(parents=True, exist_ok=True)
    url = f"{UPSTREAM}/releases/download/{args.tag}/{args.asset}"

    with tempfile.TemporaryDirectory(prefix="streamiov-ffmpeg-") as temporary:
        archive = pathlib.Path(temporary) / args.asset
        print(f"Downloading pinned FFmpeg runtime: {url}", flush=True)
        download(url, archive)
        actual = sha256(archive)
        if actual.lower() != args.sha256.lower():
            raise RuntimeError(f"FFmpeg archive checksum mismatch: expected {args.sha256}, got {actual}")
        executable = binary_dir / executable_name
        extract_binary(archive, is_windows, executable)

    if is_windows:
        expected_machine = 0x8664 if args.target == "win64" else 0xAA64
        actual_machine = pe_machine(executable)
        if actual_machine != expected_machine:
            raise RuntimeError(f"Wrong Windows FFmpeg architecture: expected PE {expected_machine:#06x}, got {actual_machine:#06x}")
    else:
        executable.chmod(0o755)

    # Windows ARM64 is cross-built on the x64 GitHub runner and cannot be executed there.
    if args.target != "winarm64":
        version = run(executable, "-version")
        encoders = run(executable, "-hide_banner", "-encoders")
        protocols = run(executable, "-hide_banner", "-protocols")
        buildconf = run(executable, "-hide_banner", "-buildconf")
        if "libx264" not in encoders or " aac " not in encoders:
            raise RuntimeError("FFmpeg is missing required libx264 or native AAC encoders")
        if not any(line.strip().startswith("rtmp") for line in protocols.splitlines()):
            raise RuntimeError("FFmpeg is missing RTMP protocol support")
        if "--enable-nonfree" in buildconf:
            raise RuntimeError("Refusing to package an unredistributable --enable-nonfree build")
        if "--enable-gpl" not in buildconf or "--enable-version3" not in buildconf:
            raise RuntimeError("FFmpeg build does not declare the expected GPLv3 configuration")
        version_line = next((line.strip() for line in version.splitlines()
                             if line.startswith("ffmpeg version")), "unknown")
    else:
        version_line = "Runtime execution deferred: Windows ARM64 binary cross-built on x64 runner"

    license_url = f"https://raw.githubusercontent.com/FFmpeg/FFmpeg/{args.source_commit}/COPYING.GPLv3"
    license_path = runtime_dir / "COPYING.GPLv3"
    download(license_url, license_path)
    if license_path.stat().st_size < 10000:
        raise RuntimeError("FFmpeg GPLv3 license text download is incomplete")

    metadata = {
        "runtime": "FFmpeg",
        "variant": "GPL static",
        "upstream_release_tag": args.tag,
        "upstream_asset": args.asset,
        "archive_sha256": actual,
        "ffmpeg_source_commit": args.source_commit,
        "ffmpeg_source_url": f"{FFMPEG_SOURCE}/tree/{args.source_commit}",
        "build_scripts_commit": args.build_scripts_commit,
        "build_scripts_url": f"{UPSTREAM}/tree/{args.build_scripts_commit}",
        "binary": f"bin/{executable_name}",
        "target": args.target,
        "version": version_line,
        "verification": "PE architecture checked; runtime execution deferred for Windows ARM64" if args.target == "winarm64" else "native execution verified: libx264, native AAC, RTMP, GPLv3, no nonfree",
        "license": "GPL-3.0-or-later; complete corresponding source and dependency notices must accompany redistribution",
    }
    (runtime_dir / "BUILD-INFO.json").write_text(json.dumps(metadata, indent=2) + chr(10), encoding="utf-8")
    print(json.dumps(metadata, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"FFmpeg runtime preparation failed: {error}", file=sys.stderr)
        raise
