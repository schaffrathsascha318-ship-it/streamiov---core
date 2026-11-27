#!/usr/bin/env python3
"""Build a reproducible FFmpeg corresponding-source bundle for the pinned GPL runtime."""
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.parse
import zipfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
GENERATOR_VERSION = "ffmpeg-source-bundle-1.0"
TARGETS = ("win64", "winarm64", "linux64", "linuxarm64")
BINARY_ASSETS = (
    {
        "name": "ffmpeg-N-129219-g359c825152-win64-gpl.zip",
        "sha256": "af969e0dda60550d75a393a575bad7be6ca7be8e698baa1c80f4963250acc969",
        "target": "win64",
    },
    {
        "name": "ffmpeg-N-129219-g359c825152-winarm64-gpl.zip",
        "sha256": "94c08d75532f5b450f8562871452a863ffeaba66659b740eec85aadf4b6148c4",
        "target": "winarm64",
    },
    {
        "name": "ffmpeg-N-129219-g359c825152-linux64-gpl.tar.xz",
        "sha256": "bcc1539edf917320fd3eb83bd5ab4d0a5ff686980d4717e802e346279beb1f30",
        "target": "linux64",
    },
    {
        "name": "ffmpeg-N-129219-g359c825152-linuxarm64-gpl.tar.xz",
        "sha256": "84ebc321674db39637175861ccfaf840b953bda2f115d7de77dddf155a2f11f6",
        "target": "linuxarm64",
    },
)

README = """Streamiov Studio FFmpeg corresponding-source bundle

This archive is generated from the exact revisions pinned by Streamiov Studio's
native installer workflow. It contains:

  ffmpeg/                complete FFmpeg source tree at the pinned source commit
  ffmpeg-build-scripts/  complete FFmpeg-Builds tree at the pinned scripts commit
  dependencies/          source trees for every repository/revision referenced by
                         the pinned build scripts, including references used only
                         by non-GPL variants
  configure/             Dockerfiles generated for the four shipped GPL targets
  upstream-release.txt   pinned binary asset names and their SHA-256 checksums
  COPYING.GPLv3          FFmpeg GPLv3 license text
  MANIFEST.json          exact revisions, retrieval methods and archive hashes

The shipped binaries use the GPL static variants and are checked for the absence
of --enable-nonfree. Some source references in the build-scripts tree belong to
nonfree variants; they are included for completeness but are not linked into the
shipped binaries. See MANIFEST.json for the exact pinned revisions.
"""


def run(command: list[str], *, cwd: pathlib.Path | None = None, timeout: int = 900) -> str:
    completed = subprocess.run(
        command,
        cwd=str(cwd) if cwd else None,
        check=True,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return completed.stdout + completed.stderr


def sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def download(url: str, destination: pathlib.Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.unlink(missing_ok=True)
    command = [
        "curl",
        "-fsSL",
        "--retry",
        "5",
        "--retry-all-errors",
        "--connect-timeout",
        "30",
        "--max-time",
        "900",
        "-A",
        "Streamiov-FFmpeg-source-bundle",
        "-o",
        str(destination),
        url,
    ]
    subprocess.run(command, check=True, capture_output=True, text=True, timeout=960)


def safe_extract(archive: pathlib.Path, destination: pathlib.Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as bundle:
            bundle.extractall(destination)
        return
    with tarfile.open(archive, "r:*") as bundle:
        try:
            bundle.extractall(destination, filter="data")
        except TypeError:
            bundle.extractall(destination)


def strip_root(destination: pathlib.Path) -> None:
    entries = sorted(item for item in destination.iterdir() if item.name not in {".", ".."})
    if len(entries) != 1 or not entries[0].is_dir():
        return
    root = entries[0]
    for item in sorted(root.iterdir()):
        target = destination / item.name
        if target.exists():
            if target.is_dir() and not target.is_symlink():
                shutil.rmtree(target)
            else:
                target.unlink()
        shutil.move(str(item), str(target))
    root.rmdir()


def normalize_tree(root: pathlib.Path) -> None:
    for current, directories, files in os.walk(root, topdown=False):
        current_path = pathlib.Path(current)
        for name in directories:
            if name in {".git", ".svn", ".hg", ".bzr", "__pycache__", ".cache", "node_modules"}:
                target = current_path / name
                if target.is_symlink():
                    target.unlink()
                else:
                    shutil.rmtree(target, ignore_errors=True)
        for name in files:
            if name.endswith((".pyc", ".pyo", ".log", ".pid")):
                (current_path / name).unlink(missing_ok=True)
                continue
            target = current_path / name
            if target.is_symlink():
                continue
            try:
                mode = target.stat().st_mode
            except FileNotFoundError:
                continue
            target.chmod(0o755 if mode & 0o111 else 0o644)


def parse_pins(build_scripts: pathlib.Path) -> list[dict[str, str]]:
    pins: dict[tuple[str, str], dict[str, str]] = {}
    for script in sorted(build_scripts.rglob("*.sh")):
        text = script.read_text(encoding="utf-8", errors="replace")
        repos = {
            int(match.group(1) or 0): match.group(2)
            for match in re.finditer(r'^SCRIPT_REPO(\d*)="([^"]+)"', text, re.M)
        }
        commits = {
            int(match.group(1) or 0): match.group(2)
            for match in re.finditer(r'^SCRIPT_COMMIT(\d*)="([^"]+)"', text, re.M)
        }
        revisions = {
            int(match.group(1) or 0): match.group(2)
            for match in re.finditer(r'^SCRIPT_REV(\d*)="([^"]+)"', text, re.M)
        }
        branches = {
            int(match.group(1) or 0): match.group(2)
            for match in re.finditer(r'^SCRIPT_BRANCH(\d*)="([^"]+)"', text, re.M)
        }
        tags = {
            int(match.group(1) or 0): match.group(2)
            for match in re.finditer(r'^SCRIPT_TAG\w*(\d*)="([^"]+)"', text, re.M)
        }
        for index, url in repos.items():
            revision = commits.get(index) or revisions.get(index) or branches.get(index) or tags.get(index)
            if not revision:
                continue
            key = (url.rstrip("/"), revision)
            pin = pins.setdefault(
                key,
                {
                    "url": key[0],
                    "revision": revision,
                    "first_script": str(script.relative_to(build_scripts)),
                },
            )
            if str(script.relative_to(build_scripts)) < pin["first_script"]:
                pin["first_script"] = str(script.relative_to(build_scripts))
    return sorted(pins.values(), key=lambda item: (item["url"], item["revision"]))


def pin_slug(pin: dict[str, str]) -> str:
    parsed = urllib.parse.urlparse(pin["url"])
    path = re.sub(r"\.git$", "", parsed.path.strip("/"))
    name = path.split("/")[-1] if path else parsed.netloc
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-") or "source"
    digest = sha256_text(f"{pin['url']}\n{pin['revision']}")[:12]
    return f"{safe_name}-{digest}"


def archive_url(pin: dict[str, str]) -> str | None:
    parsed = urllib.parse.urlparse(pin["url"])
    revision = urllib.parse.quote(pin["revision"], safe="")
    host = parsed.netloc.lower()
    path = parsed.path.strip("/")
    if host == "github.com":
        return f"https://codeload.github.com/{path.removesuffix('.git')}/tar.gz/{revision}"
    if host.endswith("googlesource.com"):
        return f"https://{host}/{path}/+archive/{revision}.tar.gz"
    if host in {"gitlab.com", "gitlab.freedesktop.org", "code.videolan.org"}:
        project = path.removesuffix(".git")
        name = project.split("/")[-1]
        return f"https://{host}/{project}/-/archive/{revision}/{name}-{revision}.tar.gz"
    return None


def fetch_git(pin: dict[str, str], destination: pathlib.Path, temporary: pathlib.Path) -> str:
    work = temporary / f"{pin_slug(pin)}-git"
    run(["git", "init", "--quiet", str(work)])
    run(["git", "-C", str(work), "remote", "add", "origin", pin["url"]])
    try:
        run(["git", "-C", str(work), "fetch", "--quiet", "--depth", "1", "origin", pin["revision"]])
        reference = "FETCH_HEAD"
    except subprocess.CalledProcessError:
        run(["git", "-C", str(work), "fetch", "--quiet", "--filter=blob:none", "origin"])
        reference = pin["revision"]
    run(["git", "-C", str(work), "checkout", "--quiet", "--force", reference])
    resolved = run(["git", "-C", str(work), "rev-parse", "HEAD"]).strip()
    shutil.move(str(work), str(destination))
    return resolved


def fetch_svn(pin: dict[str, str], destination: pathlib.Path) -> str:
    run([
        "svn",
        "export",
        "--non-interactive",
        "--username",
        "anonymous",
        "--password",
        "",
        "--quiet",
        "--force",
        "-r",
        pin["revision"],
        pin["url"],
        str(destination),
    ])
    return pin["revision"]


def fetch_pin(pin: dict[str, str], temporary: pathlib.Path) -> dict[str, str]:
    slug = pin_slug(pin)
    destination = temporary / "dependencies" / slug
    destination.parent.mkdir(parents=True, exist_ok=True)
    url = archive_url(pin)
    record = dict(pin)
    record["slug"] = slug
    record["source_path"] = f"dependencies/{slug}"
    if url:
        archive = temporary / "archives" / f"{slug}.tar.gz"
        archive.parent.mkdir(parents=True, exist_ok=True)
        print(f"Fetching {pin['url']}@{pin['revision']}", flush=True)
        try:
            download(url, archive)
        except subprocess.CalledProcessError:
            print(f"Archive fetch failed; cloning {pin['url']}@{pin['revision']}", flush=True)
            record["retrieval_method"] = "git-fallback"
            record["retrieval_url"] = pin["url"]
            record["resolved_revision"] = fetch_git(pin, destination, temporary)
        else:
            record["retrieval_method"] = "archive"
            record["retrieval_url"] = url
            record["retrieval_sha256"] = sha256(archive)
            safe_extract(archive, destination)
            strip_root(destination)
    elif pin["url"].startswith("https://svn.code.sf.net/") or pin["url"].startswith("https://svn.xvid.org/"):
        print(f"Exporting {pin['url']}@{pin['revision']}", flush=True)
        record["retrieval_method"] = "svn"
        record["retrieval_url"] = pin["url"]
        record["resolved_revision"] = fetch_svn(pin, destination)
    else:
        print(f"Cloning {pin['url']}@{pin['revision']}", flush=True)
        record["retrieval_method"] = "git"
        record["retrieval_url"] = pin["url"]
        record["resolved_revision"] = fetch_git(pin, destination, temporary)
    normalize_tree(destination)
    if not any(destination.rglob("*")):
        raise RuntimeError(f"empty source tree for {pin['url']}")
    return record


def generate_configs(build_scripts: pathlib.Path, configure_dir: pathlib.Path) -> None:
    configure_dir.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    environment["LC_ALL"] = "C.UTF-8"
    environment["GITHUB_REPOSITORY"] = "ffmpeg-builds/ffmpeg-builds"
    environment["REGISTRY_OVERRIDE"] = "ghcr.io"
    for target in TARGETS:
        dockerfile = build_scripts / "Dockerfile"
        dockerfile.unlink(missing_ok=True)
        print(f"Generating build configuration for {target}-gpl", flush=True)
        run(["./generate.sh", target, "gpl"], cwd=build_scripts, timeout=300)
        if not dockerfile.is_file():
            raise RuntimeError(f"generate.sh produced no Dockerfile for {target}")
        shutil.copyfile(dockerfile, configure_dir / f"{target}-gpl.Dockerfile")
        dockerfile.unlink(missing_ok=True)


def add_tree(archive: tarfile.TarFile, root: pathlib.Path, prefix: pathlib.Path) -> None:
    info = tarfile.TarInfo(str(prefix))
    info.type = tarfile.DIRTYPE
    info.mtime = 0
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    info.mode = 0o755
    archive.addfile(info)
    for source in sorted(root.rglob("*")):
        relative = source.relative_to(root)
        target_name = str(prefix / relative)
        info = archive.gettarinfo(str(source), arcname=target_name)
        info.mtime = 0
        info.uid = 0
        info.gid = 0
        info.uname = ""
        info.gname = ""
        info.pax_headers = {}
        if source.is_symlink():
            info.type = tarfile.SYMTYPE
            info.linkname = os.readlink(source)
            info.size = 0
            info.mode = 0o777
        elif source.is_dir():
            info.type = tarfile.DIRTYPE
            info.size = 0
            info.mode = 0o755
        else:
            info.type = tarfile.REGTYPE
            info.mode = 0o755 if source.stat().st_mode & 0o111 else 0o644
        handle = None
        if info.isfile():
            handle = source.open("rb")
        archive.addfile(info, handle)
        if handle is not None:
            handle.close()


def build_tar(bundle_root: pathlib.Path, target: pathlib.Path) -> str:
    prefix = pathlib.Path("ffmpeg-source-bundle")
    with tarfile.open(target, "w:xz", preset=6, format=tarfile.GNU_FORMAT) as archive:
        add_tree(archive, bundle_root, prefix)
    return sha256(target)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-commit", default="359c825152")
    parser.add_argument("--build-scripts-commit", default="7f2a6b1050d302144de8366afa37a75e46f326aa")
    parser.add_argument("--release-tag", default="autobuild-2026-11-22-12-36")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()

    output = pathlib.Path(args.output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="streamiov-ffmpeg-source-") as temporary_text:
        temporary = pathlib.Path(temporary_text)
        ffmpeg_archive = temporary / "ffmpeg.tar.gz"
        build_scripts_archive = temporary / "ffmpeg-build-scripts.tar.gz"
        ffmpeg_url = f"https://codeload.github.com/FFmpeg/FFmpeg/tar.gz/{urllib.parse.quote(args.source_commit, safe='')}"
        build_scripts_url = (
            "https://codeload.github.com/FFmpeg-Builds/FFmpeg-Builds/tar.gz/"
            f"{urllib.parse.quote(args.build_scripts_commit, safe='')}"
        )
        print(f"Fetching pinned FFmpeg source: {ffmpeg_url}", flush=True)
        download(ffmpeg_url, ffmpeg_archive)
        print(f"Fetching pinned build scripts: {build_scripts_url}", flush=True)
        download(build_scripts_url, build_scripts_archive)

        extracted = temporary / "extracted"
        ffmpeg_source = extracted / "ffmpeg"
        build_scripts = extracted / "ffmpeg-build-scripts"
        safe_extract(ffmpeg_archive, ffmpeg_source)
        strip_root(ffmpeg_source)
        safe_extract(build_scripts_archive, build_scripts)
        strip_root(build_scripts)
        normalize_tree(ffmpeg_source)
        normalize_tree(build_scripts)

        pins = parse_pins(build_scripts)
        records: list[dict[str, str]] = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = {executor.submit(fetch_pin, pin, temporary): pin for pin in pins}
            for future in concurrent.futures.as_completed(futures):
                pin = futures[future]
                try:
                    record = future.result()
                except Exception as error:
                    raise RuntimeError(f"source fetch failed for {pin['url']}@{pin['revision']}: {error}") from error
                records.append(record)

        bundle_root = temporary / "bundle"
        bundle_root.mkdir(parents=True, exist_ok=True)
        shutil.copytree(ffmpeg_source, bundle_root / "ffmpeg")
        shutil.copytree(build_scripts, bundle_root / "ffmpeg-build-scripts")
        shutil.copytree(temporary / "dependencies", bundle_root / "dependencies")
        generate_configs(build_scripts, bundle_root / "configure")
        (bundle_root / "README.txt").write_text(README, encoding="utf-8")
        (bundle_root / "upstream-release.txt").write_text(
            "\n".join(
                f"{asset['name']}  {asset['sha256']}  {asset['target']}" for asset in BINARY_ASSETS
            ) + "\n",
            encoding="utf-8",
        )
        shutil.copyfile(ffmpeg_source / "COPYING.GPLv3", bundle_root / "COPYING.GPLv3")

        manifest = {
            "generator_version": GENERATOR_VERSION,
            "upstream_release_tag": args.release_tag,
            "upstream_release_url": f"https://github.com/FFmpeg-Builds/FFmpeg-Builds/releases/tag/{args.release_tag}",
            "ffmpeg_source_commit": args.source_commit,
            "ffmpeg_source_url": f"https://github.com/FFmpeg/FFmpeg/tree/{args.source_commit}",
            "build_scripts_commit": args.build_scripts_commit,
            "build_scripts_url": f"https://github.com/FFmpeg-Builds/FFmpeg-Builds/tree/{args.build_scripts_commit}",
            "binary_assets": list(BINARY_ASSETS),
            "targets": list(TARGETS),
            "dependencies": records,
        }
        (bundle_root / "MANIFEST.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        archive = output / "ffmpeg-source-bundle.tar.xz"
        digest = build_tar(bundle_root, archive)
        (output / "SHA256SUMS.txt").write_text(
            f"{digest}  ffmpeg-source-bundle.tar.xz\n",
            encoding="utf-8",
        )
        print(json.dumps({
            "archive": str(archive),
            "bytes": archive.stat().st_size,
            "sha256": digest,
            "dependencies": len(records),
        }, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"FFmpeg source bundle build failed: {error}", file=sys.stderr)
        raise
