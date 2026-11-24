"""Ordered provider routing for the Streamiov Core model runtime.

Only explicitly configured providers are used. A failed provider (including a
Cloudflare 429 quota response) cannot prevent the router from trying the next
configured local/self-hosted provider.
"""
from __future__ import annotations

from typing import Iterable

from .base import ModelReply, ModelProvider
from .local_http import ProviderError


class ProviderRouter:
    """Try configured providers in order and expose a secret-free health report."""

    def __init__(self, providers: Iterable[tuple[str, ModelProvider]]) -> None:
        configured = list(providers)
        if not configured:
            raise ProviderError("At least one Streamiov model provider must be configured.")
        names = [name for name, _provider in configured]
        if any(not isinstance(name, str) or not name.strip() for name in names):
            raise ProviderError("Provider names must be non-empty strings.")
        if len(set(names)) != len(names):
            raise ProviderError("A model provider may only appear once in the provider order.")
        if any(not callable(getattr(provider, "generate", None)) for _name, provider in configured):
            raise ProviderError("Every configured model provider must implement generate().")
        self.providers = configured

    def check_ready(self) -> dict:
        statuses = []
        for name, provider in self.providers:
            check = getattr(provider, "check_ready", None)
            if not callable(check):
                statuses.append({
                    "provider": name,
                    "ready": False,
                    "reachable": False,
                    "model_available": False,
                    "detail": "Provider does not expose a health check.",
                })
                continue
            try:
                status = check()
                if not isinstance(status, dict):
                    raise ProviderError("Provider health response must be an object.")
                # Provider identity is assigned by the router, not trusted from
                # an adapter response. Adapter status must never include secrets.
                statuses.append({**status, "provider": name})
            except ProviderError as exc:
                statuses.append({
                    "provider": name,
                    "ready": False,
                    "reachable": False,
                    "model_available": False,
                    "detail": f"Health check failed: {type(exc).__name__}.",
                })
        active = next((item["provider"] for item in statuses if item.get("ready") is True), None)
        return {
            "provider": "streamiov-provider-router",
            "ready": active is not None,
            "active_provider": active,
            "providers": statuses,
            "detail": "A configured model provider is ready." if active else "No configured model provider is ready.",
        }

    def generate(self, *, system: str, messages: list[dict[str, str]]) -> ModelReply:
        failures = []
        for name, provider in self.providers:
            try:
                reply = provider.generate(system=system, messages=messages)
                if not isinstance(reply, ModelReply):
                    raise ProviderError("Provider returned an invalid model reply.")
                return reply
            except ProviderError as exc:
                # Adapter exceptions are already sanitized at their boundary.
                # Keep diagnostics bounded so a failing endpoint cannot flood logs.
                detail = " ".join(str(exc).split())[:400]
                failures.append(f"{name}: {detail or type(exc).__name__}")
        raise ProviderError(
            "All configured Streamiov model providers failed. "
            + " | ".join(failures)
        )
