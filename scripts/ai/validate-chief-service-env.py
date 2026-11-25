#!/usr/bin/env python3
"""Fail-fast validation for the persistent AI Chief systemd service environment."""
from __future__ import annotations

import os
from urllib.parse import urlsplit


PINNED_CLOUDFLARE_MODEL = "@cf/zai-org/glm-4.7-flash"


def validate_environment(env: dict[str, str]) -> str | None:
    goal = env.get("STREAMIOV_PROJECT_GOAL", "").strip()
    if not goal or len(goal) > 8000:
        return "STREAMIOV_PROJECT_GOAL must contain 1–8000 characters."

    provider = env.get("STREAMIOV_MODEL_PROVIDER", "ollama").strip().lower()
    model = env.get("STREAMIOV_MODEL", "qwen2.5-coder:7b").strip()
    if not model:
        return "STREAMIOV_MODEL must not be empty."

    if provider == "cloudflare-workers-ai":
        if model != PINNED_CLOUDFLARE_MODEL:
            return "Cloudflare provider must use the pinned Streamiov AI Worker model."
        token = env.get("STREAMIOV_AI_WORKER_TOKEN", "")
        if len(token) < 32 or token.startswith("REPLACE_"):
            return "STREAMIOV_AI_WORKER_TOKEN is missing or still contains a placeholder."
        raw_url = env.get("STREAMIOV_MODEL_URL", "").strip()
        try:
            parsed = urlsplit(raw_url)
            port = parsed.port
        except ValueError:
            return "STREAMIOV_MODEL_URL is malformed."
        host = (parsed.hostname or "").lower()
        if (
            parsed.scheme != "https"
            or not (host == "workers.dev" or host.endswith(".workers.dev"))
            or "replace_with" in host
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in ("", "/")
            or parsed.query
            or parsed.fragment
            or port not in (None, 443)
        ):
            return "STREAMIOV_MODEL_URL must be the real HTTPS origin of the Streamiov workers.dev AI gateway."
    elif provider not in {"ollama", "openai-compatible-local"}:
        return "STREAMIOV_MODEL_PROVIDER must be cloudflare-workers-ai, ollama, or openai-compatible-local."
    return None


def main() -> int:
    error = validate_environment(dict(os.environ))
    if error:
        print("AI Chief service configuration invalid: " + error)
        return 2
    print("AI Chief service environment is structurally valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
