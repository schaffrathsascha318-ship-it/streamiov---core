#!/usr/bin/env python3
"""Validate the repository's Cloudflare configs without contacting Cloudflare.

This check is deliberately offline. It proves that the checked-in Worker
sources, asset directory, deployment scripts, and public download references
are internally consistent. It does not prove that an account, token, Workers AI
binding, custom domain, or live deployment exists.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
HOMEPAGE_CONFIG = ROOT / "dist" / "streamiov-homepage-worker" / "wrangler.jsonc"
HOMEPAGE_PUBLIC = ROOT / "dist" / "streamiov-homepage-worker" / "public"
AI_CONFIG = ROOT / "infrastructure" / "cloudflare" / "streamiov-ai-worker" / "wrangler.jsonc"
AI_SOURCE = ROOT / "infrastructure" / "cloudflare" / "streamiov-ai-worker" / "src" / "index.mjs"
DEPLOY_SCRIPT = ROOT / "scripts" / "deploy-streamiov-ai-worker.sh"
DEPLOY_WORKFLOW = ROOT / ".github" / "workflows" / "cloudflare-deploy.yml"
CHECKS_WORKFLOW = ROOT / ".github" / "workflows" / "cloudflare-checks.yml"
DOWNLOAD_PAGE = HOMEPAGE_PUBLIC / "download" / "index.html"
DOWNLOADS = HOMEPAGE_PUBLIC / "downloads"
PINNED_MODEL = "@cf/zai-org/glm-4.7-flash"


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


def verify() -> dict[str, Any]:
    errors: list[str] = []
    checks: list[str] = []

    for path in (HOMEPAGE_CONFIG, AI_CONFIG, AI_SOURCE, DEPLOY_SCRIPT, DEPLOY_WORKFLOW, CHECKS_WORKFLOW):
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
            "app/index.html",
            "assets/streamiov-wordmark.svg",
            "assets/streamiov-symbol.svg",
        ):
            if not (HOMEPAGE_PUBLIC / required).is_file():
                errors.append(f"homepage public file is missing: {required}")
        checks.append("homepage asset tree contains the public entry points")

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
        "inputs.confirm",
        "pages deploy",
        "--project-name streamiov",
        "wrangler@4 deploy --config infrastructure/cloudflare/streamiov-ai-worker/wrangler.jsonc",
    ):
        if required not in workflow_text:
            errors.append(f"cloudflare-deploy.yml is missing: {required}")
    if re.search(r"^  (push|pull_request):", workflow_text, flags=re.M):
        errors.append("cloudflare-deploy.yml must stay manual and must not run on push or pull_request")
    if "Deploy homepage assets Worker" in workflow_text:
        errors.append("cloudflare-deploy.yml still deploys the homepage Worker instead of the Pages project")
    checks.append("manual deploy workflow targets the streamiov Pages project and the AI Worker")

    checks_text = CHECKS_WORKFLOW.read_text(encoding="utf-8")
    if "python scripts/verify-cloudflare-config.py" not in checks_text:
        errors.append("cloudflare-checks.yml does not run the offline verifier")
    if "contents: read" not in checks_text:
        errors.append("cloudflare-checks.yml must declare read-only contents permission")
    checks.append("read-only Cloudflare workflow runs the offline verifier")

    if DOWNLOAD_PAGE.is_file():
        markup = DOWNLOAD_PAGE.read_text(encoding="utf-8")
        targets = re.findall(r'href="(/downloads/[^"#?]+)"', markup)
        if not targets:
            errors.append("download page does not link any local /downloads/ file")
        for target in sorted(set(targets)):
            path = HOMEPAGE_PUBLIC / target.lstrip("/")
            if not path.is_file():
                errors.append(f"download page links a missing file: {target}")
        checks.append(f"download page links {len(set(targets))} existing local files")

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
