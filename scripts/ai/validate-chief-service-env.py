#!/usr/bin/env python3
"""Fail-fast validation for the persistent AI Chief systemd service environment."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from urllib.parse import urlsplit

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from ai.providers.local_http import ProviderError  # noqa: E402
from ai.providers.self_hosted import _endpoint_url  # noqa: E402


PINNED_CLOUDFLARE_MODEL = "@cf/zai-org/glm-4.7-flash"
PROVIDER_KINDS = (
    "ollama",
    "openai-compatible-local",
    "self-hosted-openai-compatible",
    "cloudflare-workers-ai",
)


def _configured_provider_kinds(env: dict[str, str]) -> tuple[str, ...] | str:
    provider_order = env.get("STREAMIOV_MODEL_PROVIDERS", "").strip()
    if provider_order:
        kinds = tuple(item.strip().lower() for item in provider_order.split(","))
        if not kinds or any(not item for item in kinds):
            return "STREAMIOV_MODEL_PROVIDERS must be a comma-separated provider list."
        if len(set(kinds)) != len(kinds):
            return "STREAMIOV_MODEL_PROVIDERS cannot contain duplicate providers."
    else:
        kinds = (env.get("STREAMIOV_MODEL_PROVIDER", "ollama").strip().lower(),)
    unknown = [item for item in kinds if item not in PROVIDER_KINDS]
    if unknown:
        return "STREAMIOV_MODEL_PROVIDER/STREAMIOV_MODEL_PROVIDERS must be one of: " + ", ".join(PROVIDER_KINDS) + "."
    return kinds


def _validate_cloudflare(env: dict[str, str], model: str) -> str | None:
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
    return None


def _validate_self_hosted(env: dict[str, str]) -> str | None:
    model = env.get("STREAMIOV_SELF_HOSTED_MODEL", "").strip()
    if not model:
        return "STREAMIOV_SELF_HOSTED_MODEL must name a model."
    token = env.get("STREAMIOV_SELF_HOSTED_MODEL_TOKEN", "")
    if len(token) < 32 or token.startswith("REPLACE_"):
        return "STREAMIOV_SELF_HOSTED_MODEL_TOKEN is missing or still contains a placeholder."
    try:
        _endpoint_url(env.get("STREAMIOV_SELF_HOSTED_MODEL_URL", "").strip())
    except ProviderError:
        return "STREAMIOV_SELF_HOSTED_MODEL_URL must be a named HTTPS origin without credentials, query strings, or custom ports."
    return None


def _validate_recovery(env: dict[str, str]) -> str | None:
    for name in (
        "STREAMIOV_PROVIDER_RECOVERY_COOLDOWN_SECONDS",
        "STREAMIOV_PROVIDER_MAX_COOLDOWN_SECONDS",
    ):
        raw = env.get(name, "").strip()
        if not raw:
            continue
        try:
            value = float(raw)
        except ValueError:
            return f"{name} must be a positive number of seconds."
        if not 0 < value <= 24 * 60 * 60:
            return f"{name} must be between 1 and 86400 seconds."
    return None


def validate_environment(env: dict[str, str]) -> str | None:
    goal = env.get("STREAMIOV_PROJECT_GOAL", "").strip()
    if not goal:
        goal = env.get("STREAMIOV_AI_PROJECT_GOAL", "").strip()
    if not goal or len(goal) > 8000:
        return "STREAMIOV_PROJECT_GOAL or STREAMIOV_AI_PROJECT_GOAL must contain 1–8000 characters."

    kinds = _configured_provider_kinds(env)
    if isinstance(kinds, str):
        return kinds
    recovery_error = _validate_recovery(env)
    if recovery_error:
        return recovery_error
    model = env.get("STREAMIOV_MODEL", "qwen2.5-coder:7b").strip()
    if not model:
        return "STREAMIOV_MODEL must not be empty."
    if "cloudflare-workers-ai" in kinds:
        error = _validate_cloudflare(env, model)
        if error:
            return error
    if "self-hosted-openai-compatible" in kinds:
        error = _validate_self_hosted(env)
        if error:
            return error
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
