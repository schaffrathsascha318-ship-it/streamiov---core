"""Authenticated HTTPS client for a self-hosted OpenAI-compatible model endpoint."""
from __future__ import annotations

import json
import os
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .base import ModelReply
from .local_http import ProviderError

MAX_REQUEST_BYTES = 64 * 1024
MAX_PROMPT_CHARS = 48_000
MAX_MESSAGE_CHARS = 32_000


def _endpoint_url(value: str) -> str:
    if not isinstance(value, str) or not value:
        raise ProviderError("STREAMIOV_SELF_HOSTED_MODEL_URL must be configured.")
    try:
        parsed = urlparse(value)
        port = parsed.port
    except ValueError as exc:
        raise ProviderError("Self-hosted model endpoint URL is malformed.") from exc
    host = parsed.hostname or ""
    if (
        parsed.scheme != "https"
        or not host
        or "." not in host
        or host in {"localhost"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or port not in (None, 443)
    ):
        raise ProviderError("Self-hosted model endpoint must use HTTPS on a named host, without credentials, query strings, or custom ports.")
    return value.rstrip("/")


class SelfHostedOpenAIProvider:
    """Calls an explicitly configured, bearer-authenticated self-hosted model gateway."""

    def __init__(self, model: str, base_url: str, token: str) -> None:
        if not isinstance(model, str) or not model.strip():
            raise ProviderError("STREAMIOV_SELF_HOSTED_MODEL must name a model.")
        if not isinstance(token, str) or len(token) < 32:
            raise ProviderError("STREAMIOV_SELF_HOSTED_MODEL_TOKEN must contain at least 32 characters.")
        self.model = model.strip()
        self.base_url = _endpoint_url(base_url)
        self.token = token

    def _request(self, method: str, path: str, payload: dict | None = None) -> dict:
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        if data is not None and len(data) > MAX_REQUEST_BYTES:
            raise ProviderError(f"Self-hosted model request exceeds {MAX_REQUEST_BYTES} bytes.")
        request = Request(
            self.base_url + path,
            data=data,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {self.token}",
                **({"Content-Type": "application/json"} if data is not None else {}),
            },
            method=method,
        )
        try:
            with urlopen(request, timeout=120 if data is not None else 8) as response:
                result = json.loads(response.read(MAX_REQUEST_BYTES + 1).decode("utf-8"))
        except HTTPError as exc:
            # Never read or echo remote error bodies: they may contain credentials or prompts.
            raise ProviderError(f"Self-hosted model endpoint returned HTTP {exc.code}.") from None
        except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            raise ProviderError(f"Self-hosted model request failed: {type(exc).__name__}.") from None
        if not isinstance(result, dict):
            raise ProviderError("Self-hosted model endpoint returned an invalid JSON object.")
        return result

    def check_ready(self) -> dict:
        try:
            data = self._request("GET", "/v1/models")
            entries = data.get("data")
            if not isinstance(entries, list):
                raise ProviderError("Self-hosted model endpoint returned an invalid model list.")
            available = any(isinstance(item, dict) and item.get("id") == self.model for item in entries)
            return {
                "provider": "self-hosted-openai-compatible",
                "model": self.model,
                "reachable": True,
                "model_available": available,
                "models_count": len(entries),
                "ready": available,
                "detail": "Configured self-hosted model is available." if available else "Endpoint is online, but the configured model is not listed.",
            }
        except ProviderError as exc:
            return {
                "provider": "self-hosted-openai-compatible",
                "model": self.model,
                "reachable": "HTTP" not in str(exc),
                "model_available": False,
                "models_count": 0,
                "ready": False,
                "detail": str(exc),
            }

    def generate(self, *, system: str, messages: list[dict[str, str]]) -> ModelReply:
        if not isinstance(system, str) or not isinstance(messages, list):
            raise ProviderError("System prompt and messages must be text and a message list.")
        all_messages = [{"role": "system", "content": system}, *messages]
        total = 0
        for message in all_messages:
            if not isinstance(message, dict) or not isinstance(message.get("role"), str) or not isinstance(message.get("content"), str):
                raise ProviderError("Every model message must contain text role and content fields.")
            if len(message["content"]) > MAX_MESSAGE_CHARS:
                raise ProviderError(f"Model message exceeds {MAX_MESSAGE_CHARS} characters.")
            total += len(message["content"])
        if total > MAX_PROMPT_CHARS:
            raise ProviderError(f"Combined model prompt exceeds {MAX_PROMPT_CHARS} characters.")
        data = self._request("POST", "/v1/chat/completions", {
            "model": self.model,
            "temperature": 0.1,
            "stream": False,
            "messages": all_messages,
        })
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError("Self-hosted model endpoint returned an invalid chat response.") from exc
        if not isinstance(content, str) or not content.strip():
            raise ProviderError("Self-hosted model endpoint returned empty or non-text content.")
        return ModelReply(content, "self-hosted-openai-compatible", self.model)


def provider_from_env() -> SelfHostedOpenAIProvider:
    return SelfHostedOpenAIProvider(
        os.environ.get("STREAMIOV_SELF_HOSTED_MODEL", "qwen2.5-coder:7b"),
        os.environ.get("STREAMIOV_SELF_HOSTED_MODEL_URL", ""),
        os.environ.get("STREAMIOV_SELF_HOSTED_MODEL_TOKEN", ""),
    )
