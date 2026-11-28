#!/usr/bin/env python3
"""Validate the repository's Cloudflare configs without contacting Cloudflare.

This check is deliberately offline. It proves that the checked-in Worker
sources, asset directory, deployment scripts, and public download references
are internally consistent. It does not prove that an account, token, Workers AI
binding, custom domain, or live deployment exists.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
HOMEPAGE_CONFIG = ROOT / "dist" / "streamiov-homepage-worker" / "wrangler.jsonc"
HOMEPAGE_PUBLIC = ROOT / "dist" / "streamiov-homepage-worker" / "public"
AI_CONFIG = ROOT / "infrastructure" / "cloudflare" / "streamiov-ai-worker" / "wrangler.jsonc"
AI_SOURCE = ROOT / "infrastructure" / "cloudflare" / "streamiov-ai-worker" / "src" / "index.mjs"
LIBERTY_CONFIG = ROOT / "infrastructure" / "cloudflare" / "streamiov-liberty-tv-worker" / "wrangler.jsonc"
LIBERTY_SOURCE = ROOT / "infrastructure" / "cloudflare" / "streamiov-liberty-tv-worker" / "src" / "index.mjs"
LIBERTY_PUBLIC = ROOT / "infrastructure" / "cloudflare" / "streamiov-liberty-tv-worker" / "public"
DEPLOY_SCRIPT = ROOT / "scripts" / "deploy-streamiov-ai-worker.sh"
DEPLOY_WORKFLOW = ROOT / ".github" / "workflows" / "cloudflare-deploy.yml"
CHECKS_WORKFLOW = ROOT / ".github" / "workflows" / "cloudflare-checks.yml"
DOWNLOAD_PAGE = HOMEPAGE_PUBLIC / "download" / "index.html"
DOWNLOADS = HOMEPAGE_PUBLIC / "downloads"
PINNED_MODEL = "@cf/zai-org/glm-4.7-flash"
EXPECTED_RELEASE_FINGERPRINT = "2c3de4b60d60cf4c7fa19ac3378a504706f79960978dfb610d9660bc10aeb09e"


def strip_jsonc_comments(text: str) -> str:
    """Remove // and /* */ comments while preserving strings and newlines."""
    output: list[str] = []
    index = 0
    in_string = False
    escaped = False
    while index < len(text):
        char = text[index]
        next_char = text[index + 1] if index + 1 < len(text) else ""
        if in_string:
            output.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            index += 1
            continue
        if char == '"':
            in_string = True
            output.append(char)
            index += 1
            continue
        if char == "/" and next_char == "/":
            while index < len(text) and text[index] not in "\r\n":
                index += 1
            continue
        if char == "/" and next_char == "*":
            index += 2
            while index < len(text) - 1 and not (text[index] == "*" and text[index + 1] == "/"):
                if text[index] in "\r\n":
                    output.append(text[index])
                index += 1
            index += 2
            continue
        output.append(char)
        index += 1
    return "".join(output)


def release_key_fingerprint(path: Path) -> str | None:
    match = re.search(
        r"-----BEGIN PUBLIC KEY-----\s*(.+?)\s*-----END PUBLIC KEY-----",
        path.read_text(encoding="utf-8"),
        flags=re.S,
    )
    if not match:
        return None
    der = base64.b64decode("".join(match.group(1).split()), validate=True)
    return hashlib.sha256(der).hexdigest()


def verify_release_signatures(downloads: Path = DOWNLOADS) -> tuple[bool, str]:
    actual_fingerprint = release_key_fingerprint(downloads / "STREAMIOV-RELEASE-KEY.pub")
    if actual_fingerprint != EXPECTED_RELEASE_FINGERPRINT:
        return False, f"key-fingerprint: {actual_fingerprint} does not match pinned trust anchor"
    node = shutil.which("node")
    if not node:
        return False, "node is required for release signature verification"
    result = subprocess.run(
        [node, str(ROOT / "scripts" / "release-signing.mjs"), "verify-release", "--dir", str(downloads)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode == 0:
        return True, "ok"
    try:
        report = json.loads(result.stdout)
        failed = [item["check"] for item in report.get("checks", []) if not item.get("ok")]
        if failed:
            return False, "failed checks: " + ", ".join(failed)
    except (ValueError, TypeError, KeyError):
        pass
    detail = (result.stderr or result.stdout).strip().splitlines()
    return False, detail[0] if detail else "release verification failed"


def load_jsonc(path: Path) -> dict[str, Any]:
    value = json.loads(strip_jsonc_comments(path.read_text(encoding="utf-8")))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _contains_secret_like_key(value: Any) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            lowered = str(key).lower()
            if any(word in lowered for word in ("token", "secret", "password", "api_key", "apikey")):
                return True
            if _contains_secret_like_key(item):
                return True
    elif isinstance(value, list):
        return any(_contains_secret_like_key(item) for item in value)
    return False


R2_FORBIDDEN_PATTERNS = (
    re.compile(r"\br2_buckets\b", re.IGNORECASE),
    re.compile(r"\bwrangler(?:@[^\s]+)?\s+r2\b", re.IGNORECASE),
    re.compile(r"\b(?:env|context)\.R2(?:_[A-Z0-9_]+)?\b"),
    re.compile(r"\bR2_BUCKET\b", re.IGNORECASE),
    re.compile(r"\bR2Bucket\b"),
)


def find_forbidden_r2_usage(text: str) -> list[str]:
    return sorted({match.group(0) for pattern in R2_FORBIDDEN_PATTERNS for match in pattern.finditer(text)})


RELEASE_REPOSITORY = "schaffrathsascha318-ship-it/streamiov---core"
RELEASE_ASSET_SUFFIXES = (".exe", ".appimage", ".deb", ".zip", ".tar.gz", ".txt")


def find_local_download_targets(markup: str) -> list[str]:
    """Return unique local download paths referenced by the public download page."""
    return sorted(set(re.findall(r'href=["\'](/downloads/[^"\'#?]+)["\']', markup)))


def find_release_download_targets(markup: str) -> list[str]:
    """Return only direct assets hosted by this repository's GitHub Releases."""
    pattern = (
        r'href=["\']https://github\.com/'
        + re.escape(RELEASE_REPOSITORY)
        + r'/releases/download/([A-Za-z0-9._-]+)/([A-Za-z0-9._+-]+)["\']'
    )
    found = set()
    for tag, filename in re.findall(pattern, markup):
        if filename.lower().endswith(RELEASE_ASSET_SUFFIXES):
            found.add(f"https://github.com/{RELEASE_REPOSITORY}/releases/download/{tag}/{filename}")
    return sorted(found)


def verify() -> dict[str, Any]:
    errors: list[str] = []
    checks: list[str] = []

    # R2 is explicitly prohibited: do not configure buckets, bindings, SDK
    # access, or Wrangler R2 commands. Keep this guard scoped to executable
    # infrastructure/configuration, not historical documentation.
    r2_scan_roots = [ROOT / ".github" / "workflows", ROOT / "scripts", ROOT / "infrastructure" / "cloudflare"]
    r2_scan_files = sorted({
        path
        for scan_root in r2_scan_roots
        if scan_root.exists()
        for path in scan_root.rglob("*")
        if path.is_file()
        and path.resolve() != Path(__file__).resolve()
        and path.suffix.lower() in {".yml", ".yaml", ".sh", ".json", ".jsonc", ".toml", ".js", ".mjs", ".ts"}
    })
    for path in r2_scan_files:
        markers = find_forbidden_r2_usage(path.read_text(encoding="utf-8"))
        if markers:
            errors.append(f"Cloudflare R2 is prohibited but configured/referenced in {path.relative_to(ROOT)}: {', '.join(markers)}")
    checks.append("Cloudflare R2 buckets, bindings, SDK access, and Wrangler commands are prohibited")

    for path in (HOMEPAGE_CONFIG, AI_CONFIG, AI_SOURCE, LIBERTY_CONFIG, LIBERTY_SOURCE, LIBERTY_PUBLIC / "index.html", LIBERTY_PUBLIC / "site.css", DEPLOY_SCRIPT, DEPLOY_WORKFLOW, CHECKS_WORKFLOW):
        if not path.is_file():
            errors.append(f"missing required Cloudflare file: {path.relative_to(ROOT)}")
    if errors:
        return {"ok": False, "checks": checks, "errors": errors}

    try:
        homepage = load_jsonc(HOMEPAGE_CONFIG)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        errors.append(f"homepage wrangler config is invalid: {type(exc).__name__}: {exc}")
        homepage = {}
    try:
        ai = load_jsonc(AI_CONFIG)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        errors.append(f"AI wrangler config is invalid: {type(exc).__name__}: {exc}")
        ai = {}

    if homepage:
        if homepage.get("name") != "streamiov-homepage":
            errors.append("homepage Worker name must be streamiov-homepage")
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(homepage.get("compatibility_date", ""))):
            errors.append("homepage compatibility_date must be YYYY-MM-DD")
        assets = homepage.get("assets")
        if not isinstance(assets, dict):
            errors.append("homepage config must declare an assets object")
        else:
            directory = assets.get("directory")
            if directory != "./public":
                errors.append("homepage assets.directory must be ./public")
            if (HOMEPAGE_PUBLIC / "index.html").is_file():
                checks.append("homepage index.html exists")
            else:
                errors.append("homepage public/index.html is missing")
        if "main" in homepage:
            errors.append("homepage Worker must stay assets-only and must not declare main")
        if _contains_secret_like_key(homepage):
            errors.append("homepage config contains a secret-like key")
        for required in (
            "download/index.html",
            "forum/index.html",
            "account/index.html",
            "studio/index.html",
            "assets/streamiov-wordmark.svg",
            "assets/streamiov-symbol.svg",
        ):
            if not (HOMEPAGE_PUBLIC / required).is_file():
                errors.append(f"homepage public file is missing: {required}")
        for forbidden in ("app/index.html", "app/manifest.webmanifest", "app/sw.js"):
            if (HOMEPAGE_PUBLIC / forbidden).exists():
                errors.append(f"homepage public tree still contains a browser app artifact: {forbidden}")
        for page in ("index.html", "download/index.html", "promo/index.html", "studio/index.html"):
            markup = (HOMEPAGE_PUBLIC / page).read_text(encoding="utf-8")
            if 'href="/app/"' in markup or "serviceWorker.register" in markup:
                errors.append(f"homepage page still links to a browser app: {page}")
        checks.append("homepage asset tree contains the public entry points and no browser app")

    if ai:
        if ai.get("name") != "streamiov-ai-worker":
            errors.append("AI Worker name must be streamiov-ai-worker")
        if ai.get("main") != "src/index.mjs":
            errors.append("AI Worker main must be src/index.mjs")
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(ai.get("compatibility_date", ""))):
            errors.append("AI Worker compatibility_date must be YYYY-MM-DD")
        binding = ai.get("ai")
        if not isinstance(binding, dict) or binding.get("binding") != "AI":
            errors.append("AI Worker must declare the AI binding named AI")
        if _contains_secret_like_key(ai):
            errors.append("AI Worker config contains a secret-like key")
        checks.append("AI Worker binding and entry point are configured")

    liberty = load_jsonc(LIBERTY_CONFIG)
    if liberty.get("name") != "streamiov-liberty-tv-core":
        errors.append("Liberty TV Worker name must be streamiov-liberty-tv-core")
    if liberty.get("main") != "src/index.mjs":
        errors.append("Liberty TV Worker main must be src/index.mjs")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(liberty.get("compatibility_date", ""))):
        errors.append("Liberty TV Worker compatibility_date must be YYYY-MM-DD")
    assets = liberty.get("assets")
    if not isinstance(assets, dict) or assets.get("directory") != "./public" or assets.get("binding") != "ASSETS" or assets.get("run_worker_first") is not True:
        errors.append("Liberty TV Worker must route requests through the ASSETS binding and ./public")
    if _contains_secret_like_key(liberty):
        errors.append("Liberty TV Worker config contains a secret-like key")
    liberty_source = LIBERTY_SOURCE.read_text(encoding="utf-8")
    for required in ('url.pathname === "/healthz"', 'env.ASSETS.fetch(request)', 'Content-Security-Policy', 'X-Content-Type-Options'):
        if required not in liberty_source:
            errors.append(f"Liberty TV Worker source is missing: {required}")
    if not (LIBERTY_PUBLIC / "index.html").is_file() or not (LIBERTY_PUBLIC / "site.css").is_file():
        errors.append("Liberty TV Worker public site entry point or stylesheet is missing")
    checks.append("Liberty TV Core Worker has a separate asset site, health route, and security headers")

    source = AI_SOURCE.read_text(encoding="utf-8")
    if PINNED_MODEL not in source:
        errors.append(f"AI Worker source does not pin {PINNED_MODEL}")
    if "env.AI.run" not in source:
        errors.append("AI Worker source does not call the Workers AI binding")
    for forbidden in ("api.openai.com", "api.anthropic.com", "generativelanguage.googleapis.com"):
        if forbidden in source:
            errors.append(f"AI Worker source references a non-configured provider: {forbidden}")
    if "STREAMIOV_AI_WORKER_TOKEN" not in source:
        errors.append("AI Worker source does not require its bearer token")
    if "constantTimeEqual" not in source:
        errors.append("AI Worker source does not use a constant-time token comparison")
    checks.append("AI Worker source is pinned, authenticated, and binding-only")

    deploy_text = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    for required in ("wrangler@4 deploy", "secret put STREAMIOV_AI_WORKER_TOKEN", "STREAMIOV_MODEL_PROVIDER=cloudflare-workers-ai"):
        if required not in deploy_text:
            errors.append(f"AI deploy script is missing: {required}")
    checks.append("AI deploy script sets the provider and stores the token as a secret")

    workflow_text = DEPLOY_WORKFLOW.read_text(encoding="utf-8")
    for required in (
        "workflow_dispatch:",
        "environment: production",
        "github.event_name == 'workflow_dispatch'",
        "inputs.confirm == true",
        "pages deploy",
        "--project-name streamiov",
        "wrangler@4 deploy --config infrastructure/cloudflare/streamiov-ai-worker/wrangler.jsonc",
    ):
        if required not in workflow_text:
            errors.append(f"cloudflare-deploy.yml is missing: {required}")
    trigger_block = re.search(r"(?ms)^on:\s*\n(.*?)(?=^[A-Za-z0-9_-]+:|\Z)", workflow_text)
    if not trigger_block or "workflow_dispatch:" not in trigger_block.group(1):
        errors.append("cloudflare-deploy.yml must expose the explicit manual workflow_dispatch trigger")
    elif re.search(r"(?m)^\s+push:", trigger_block.group(1)):
        errors.append("cloudflare-deploy.yml must not publish automatically on push")
    if re.search(r"^  pull_request:", workflow_text, flags=re.M):
        errors.append("cloudflare-deploy.yml must not deploy from pull_request events")
    verify_job = re.search(r"(?ms)^  verify:.*?(?=^  [a-zA-Z0-9_-]+:|\Z)", workflow_text)
    if not verify_job or "github.event_name == 'workflow_dispatch'" not in verify_job.group(0) or "inputs.confirm == true" not in verify_job.group(0):
        errors.append("Cloudflare pre-deployment verification must require a confirmed manual dispatch")
    for job_name in ("deploy-homepage", "deploy-ai-worker"):
        job = re.search(rf"(?ms)^  {job_name}:.*?(?=^  [a-zA-Z0-9_-]+:|\Z)", workflow_text)
        if not job or "needs.verify.result == 'success'" not in job.group(0) or "github.event_name == 'workflow_dispatch'" not in job.group(0) or "inputs.confirm == true" not in job.group(0):
            errors.append(f"{job_name} must require successful verification and explicit owner-confirmed manual dispatch")
    if "Deploy homepage assets Worker" in workflow_text:
        errors.append("cloudflare-deploy.yml still deploys the homepage Worker instead of the Pages project")
    checks.append("Cloudflare production deployment is manual-only, owner-confirmed, verified first, and targets the Pages project and dedicated AI Worker")

    checks_text = CHECKS_WORKFLOW.read_text(encoding="utf-8")
    if "python scripts/verify-cloudflare-config.py" not in checks_text:
        errors.append("cloudflare-checks.yml does not run the offline verifier")
    if "contents: read" not in checks_text:
        errors.append("cloudflare-checks.yml must declare read-only contents permission")
    checks.append("read-only Cloudflare workflow runs the offline verifier")

    if DOWNLOAD_PAGE.is_file():
        markup = DOWNLOAD_PAGE.read_text(encoding="utf-8")
        local_targets = find_local_download_targets(markup)
        release_targets = find_release_download_targets(markup)
        if not local_targets and not release_targets:
            errors.append("download page does not link any verified local file or approved GitHub release asset")
        for target in local_targets:
            path = HOMEPAGE_PUBLIC / target.lstrip("/")
            if not path.is_file():
                errors.append(f"download page links a missing local file: {target}")
        checks.append(
            f"download page links {len(local_targets)} local files and "
            f"{len(release_targets)} approved GitHub release assets"
        )

        release_key = DOWNLOADS / "STREAMIOV-RELEASE-KEY.pub"
        if not release_key.is_file():
            errors.append("published release key is missing")
        else:
            actual_fingerprint = release_key_fingerprint(release_key)
            if actual_fingerprint != EXPECTED_RELEASE_FINGERPRINT:
                errors.append(
                    f"published release key fingerprint {actual_fingerprint} does not match pinned fingerprint"
                )
            checks.append("published release key matches the pinned trust anchor")

        signed_ok, signed_detail = verify_release_signatures(DOWNLOADS)
        if not signed_ok:
            errors.append(f"release signature verification failed: {signed_detail}")
        checks.append("release signatures and checksums verify against the pinned trust anchor")

        if sorted(DOWNLOADS.glob("*-prototype.zip")):
            for filename in ("SHA256SUMS-games.txt", "SHA256SUMS-games.txt.sig"):
                if not (DOWNLOADS / filename).is_file():
                    errors.append(f"game prototype downloads are missing signed manifest file: {filename}")
            checks.append("game prototype downloads have a signed checksum manifest")

        if (DOWNLOADS / "streamiov-studio-part-00.bin").is_file():
            sums = (DOWNLOADS / "SHA256SUMS.txt").read_text(encoding="utf-8")
            for index in range(7):
                name = f"streamiov-studio-part-{index:02d}.bin"
                match = re.search(rf"^([0-9a-f]{{64}})  {re.escape(name)}$", sums, flags=re.M)
                if not match:
                    errors.append(f"SHA256SUMS.txt is missing {name}")
                    continue
                actual = hashlib.sha256((DOWNLOADS / name).read_bytes()).hexdigest()
                if actual != match.group(1):
                    errors.append(f"checksum mismatch for {name}")
            checks.append("source snapshot parts match SHA256SUMS.txt")
        else:
            checks.append("source snapshot parts are absent (source-only checkout); checksum verification skipped")

        game_sums = DOWNLOADS / "SHA256SUMS-games.txt"
        if game_sums.is_file():
            for line in game_sums.read_text(encoding="utf-8").splitlines():
                if not line or line.startswith("#"):
                    continue
                digest, filename = line.split(maxsplit=1)
                path = DOWNLOADS / filename
                if not path.is_file():
                    errors.append(f"game checksum file references missing file: {filename}")
                elif hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                    errors.append(f"game checksum mismatch: {filename}")
            checks.append("game prototype downloads match SHA256SUMS-games.txt")
    else:
        errors.append("download page is missing")

    headers = HOMEPAGE_PUBLIC / "_headers"
    if not headers.is_file():
        errors.append("public/_headers is missing")
    else:
        header_text = headers.read_text(encoding="utf-8")
        for required in ("X-Content-Type-Options: nosniff", "Referrer-Policy:", "X-Frame-Options:", "Permissions-Policy:"):
            if required not in header_text:
                errors.append(f"public/_headers is missing: {required}")
        checks.append("public/_headers declares baseline security headers")

    return {"ok": not errors, "checks": checks, "errors": errors}


def main() -> int:
    result = verify()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
