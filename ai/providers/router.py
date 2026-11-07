"""Explicit model failover across independently configured providers."""
from __future__ import annotations

from ai.providers.base import ModelReply, ModelProvider
from ai.providers.local_http import ProviderError


class FallbackModelProvider:
    """Try providers in order when inference fails; never hides total failure."""

    def __init__(self, primary: ModelProvider, fallbacks: tuple[ModelProvider, ...] | list[ModelProvider]):
        self.providers = (primary, *tuple(fallbacks))
        if not self.providers:
            raise ValueError("At least one model provider is required.")

    def generate(self, *, system: str, messages: list[dict[str, str]]) -> ModelReply:
        failures = []
        for provider in self.providers:
            try:
                return provider.generate(system=system, messages=messages)
            except ProviderError as exc:
                failures.append(f"{type(provider).__name__}: {str(exc)[:300]}")
        detail = "; ".join(failures)
        raise ProviderError(f"All configured model providers failed. {detail}")

    def check_ready(self) -> dict:
        checks = []
        for provider in self.providers:
            try:
                status = provider.check_ready()
            except Exception as exc:
                status = {"ready": False, "detail": f"{type(exc).__name__}: {str(exc)[:200]}"}
            checks.append(status)
        ready = any(item.get("ready") is True for item in checks)
        return {
            "provider": "fallback-router",
            "ready": ready,
            "providers": checks,
            "detail": "At least one configured provider is ready." if ready else "No configured model provider is ready.",
        }
