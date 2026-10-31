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
    parsed = urlparse(value)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ProviderError("Only plain HTTP loopback model endpoints are permitted; no paid/cloud fallback.")
    if not parsed.port:
        raise ProviderError("Local model endpoint must specify an explicit port.")
    return value.rstrip("/")

class OllamaProvider:
    def __init__(self, model: str, base_url: str = "http://127.0.0.1:11434") -> None:
        self.model = model
        self.base_url = _local_url(base_url)

    def generate(self, *, system: str, messages: list[dict[str, str]]) -> ModelReply:
        payload = {"model": self.model, "stream": False, "messages": [{"role": "system", "content": system}, *messages], "options": {"temperature": 0.1}}
        return ModelReply(_post(self.base_url + "/api/chat", payload).get("message", {}).get("content", ""), "ollama", self.model)

class LocalOpenAICompatibleProvider:
    def __init__(self, model: str, base_url: str = "http://127.0.0.1:8000/v1") -> None:
        self.model = model
        self.base_url = _local_url(base_url)

    def generate(self, *, system: str, messages: list[dict[str, str]]) -> ModelReply:
        payload = {"model": self.model, "temperature": 0.1, "messages": [{"role": "system", "content": system}, *messages]}
        data = _post(self.base_url + "/chat/completions", payload)
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError("Local OpenAI-compatible endpoint returned an invalid response.") from exc
        return ModelReply(str(content), "local-openai-compatible", self.model)

def _post(url: str, payload: dict) -> dict:
    request = Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urlopen(request, timeout=120) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        raise ProviderError(f"Local model inference failed: {type(exc).__name__}: {exc}") from exc
    if not isinstance(data, dict):
        raise ProviderError("Model endpoint response must be a JSON object.")
    return data

def provider_from_env():
    kind = os.environ.get("STREAMIOV_MODEL_PROVIDER", "ollama").lower()
    model = os.environ.get("STREAMIOV_MODEL", "qwen2.5-coder:7b")
    if kind == "ollama":
        return OllamaProvider(model, os.environ.get("STREAMIOV_MODEL_URL", "http://127.0.0.1:11434"))
    if kind == "openai-compatible-local":
        return LocalOpenAICompatibleProvider(model, os.environ.get("STREAMIOV_MODEL_URL", "http://127.0.0.1:8000/v1"))
    raise ProviderError("Unsupported provider. Choose ollama or openai-compatible-local; cloud providers are disabled.")
