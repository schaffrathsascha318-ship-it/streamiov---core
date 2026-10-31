"""Zero-cost local inference adapters. Network destinations must be loopback."""
from __future__ import annotations
import json
import os
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from .base import ModelReply


class ProviderError(RuntimeError):
    pass


def _local_url(value: str) -> str:
    if not isinstance(value, str) or not value:
        raise ProviderError("A local model endpoint URL is required.")
    try:
        parsed = urlparse(value)
        port = parsed.port
    except ValueError as exc:
        raise ProviderError("Local model endpoint URL is malformed.") from exc
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ProviderError("Only credential-free plain HTTP loopback endpoints are permitted; no paid/cloud fallback.")
    if not port:
        raise ProviderError("Local model endpoint must specify an explicit port.")
    return value.rstrip("/")


def _reply_content(data: dict, provider: str) -> str:
    try:
        content = data["message"]["content"] if provider == "ollama" else data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ProviderError(f"{provider} returned an invalid chat response.") from exc
    if not isinstance(content, str) or not content.strip():
        raise ProviderError(f"{provider} returned empty or non-text model content.")
    return content


class OllamaProvider:
    def __init__(self, model: str, base_url: str = "http://127.0.0.1:11434") -> None:
        if not isinstance(model, str) or not model.strip():
            raise ProviderError("A local model name is required.")
        self.model = model
        self.base_url = _local_url(base_url)

    def generate(self, *, system: str, messages: list[dict[str, str]]) -> ModelReply:
        payload = {
            "model": self.model,
            "stream": False,
            "messages": [{"role": "system", "content": system}, *messages],
            "options": {"temperature": 0.1},
        }
        content = _reply_content(_post(self.base_url + "/api/chat", payload), "ollama")
        return ModelReply(content, "ollama", self.model)


class LocalOpenAICompatibleProvider:
    def __init__(self, model: str, base_url: str = "http://127.0.0.1:8000/v1") -> None:
        if not isinstance(model, str) or not model.strip():
            raise ProviderError("A local model name is required.")
        self.model = model
        self.base_url = _local_url(base_url)

    def generate(self, *, system: str, messages: list[dict[str, str]]) -> ModelReply:
        payload = {
            "model": self.model,
            "temperature": 0.1,
            "messages": [{"role": "system", "content": system}, *messages],
        }
        content = _reply_content(_post(self.base_url + "/chat/completions", payload), "openai-compatible")
        return ModelReply(content, "local-openai-compatible", self.model)


def _post(url: str, payload: dict) -> dict:
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=120) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        raise ProviderError(f"Local model inference failed: {type(exc).__name__}: {exc}") from exc
    if not isinstance(data, dict):
        raise ProviderError("Local model endpoint response must be a JSON object.")
    return data


def provider_from_env():
    kind = os.environ.get("STREAMIOV_MODEL_PROVIDER", "ollama").lower()
    model = os.environ.get("STREAMIOV_MODEL", "qwen2.5-coder:7b")
    if kind == "ollama":
        return OllamaProvider(model, os.environ.get("STREAMIOV_MODEL_URL", "http://127.0.0.1:11434"))
    if kind == "openai-compatible-local":
        return LocalOpenAICompatibleProvider(model, os.environ.get("STREAMIOV_MODEL_URL", "http://127.0.0.1:8000/v1"))
    raise ProviderError("Unsupported provider. Choose ollama or openai-compatible-local; cloud providers are disabled.")
