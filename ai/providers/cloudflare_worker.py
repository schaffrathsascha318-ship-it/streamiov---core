"""Authenticated client for Streamiov's Cloudflare Workers AI gateway."""
from __future__ import annotations

import json
import os
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .base import ModelReply
from .local_http import ProviderError


class CloudflareWorkerError(ProviderError):
    def __init__(self, message: str, *, reachable: bool = False) -> None:
        super().__init__(message)
        self.reachable = reachable


DEFAULT_MODEL = "@cf/zai-org/glm-4.7-flash"


def _worker_url(value: str) -> str:
    if not isinstance(value, str) or not value:
        raise CloudflareWorkerError("STREAMIOV_MODEL_URL must be the deployed workers.dev URL.")
    try:
        parsed = urlparse(value)
        port = parsed.port
    except ValueError as exc:
        raise CloudflareWorkerError("Cloudflare Worker URL is malformed.") from exc
    host = parsed.hostname or ""
    if (
        parsed.scheme != "https"
        or not (host == "workers.dev" or host.endswith(".workers.dev"))
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in ("", "/")
        or port not in (None, 443)
    ):
        raise CloudflareWorkerError("Only HTTPS workers.dev URLs without credentials, query strings, or custom ports are allowed.")
    return value.rstrip("/")


class CloudflareWorkersAIProvider:
    def __init__(self, model: str = DEFAULT_MODEL, base_url: str = "", token: str = "") -> None:
        if model != DEFAULT_MODEL:
            raise CloudflareWorkerError(f"The Streamiov AI Worker is pinned to {DEFAULT_MODEL}.")
        if not isinstance(token, str) or len(token) < 32:
            raise CloudflareWorkerError("STREAMIOV_AI_WORKER_TOKEN must contain at least 32 characters.")
        self.model = model
        self.base_url = _worker_url(base_url)
        self.token = token

    def check_ready(self) -> dict:
        try:
            data = self._request("GET", "/health")
            ready = data.get("ok") is True and data.get("model") == self.model
            return {
                "provider": "cloudflare-workers-ai",
                "model": self.model,
                "reachable": True,
                "model_available": ready,
                "models_count": 1 if ready else 0,
                "ready": ready,
                "detail": "Authenticated Streamiov AI Worker is ready." if ready else "Worker responded, but its model configuration does not match.",
            }
        except CloudflareWorkerError as exc:
            return {
                "provider": "cloudflare-workers-ai",
                "model": self.model,
                "reachable": exc.reachable,
                "model_available": False,
                "models_count": 0,
                "ready": False,
                "detail": str(exc),
            }

    def generate(self, *, system: str, messages: list[dict[str, str]]) -> ModelReply:
        payload = {
            "model": self.model,
            "stream": False,
            "temperature": 0.1,
            "messages": [{"role": "system", "content": system}, *messages],
        }
        data = self._request("POST", "/v1/chat/completions", payload)
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise CloudflareWorkerError("Streamiov AI Worker returned an invalid chat response.") from exc
        if not isinstance(content, str) or not content.strip():
            raise CloudflareWorkerError("Streamiov AI Worker returned empty or non-text content.")
        return ModelReply(content, "cloudflare-workers-ai", self.model)

    def _request(self, method: str, path: str, payload: dict | None = None) -> dict:
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = Request(
            self.base_url + path,
            data=data,
            headers={
                "Accept": "application/json",
                # Match the verified curl request; Python-urllib was rejected at the edge.
                "User-Agent": "curl/8.0",
                "Authorization": "Bearer " + self.token,
                **({"Content-Type": "application/json"} if data is not None else {}),
            },
            method=method,
        )
        try:
            with urlopen(request, timeout=120 if method == "POST" else 10) as response:
                result = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            status = exc.code
            if status == 401:
                raise CloudflareWorkerError("Streamiov AI Worker rejected its bearer token (401).", reachable=True) from exc
            if status == 429:
                raise CloudflareWorkerError("Cloudflare Workers AI daily free allocation is exhausted (429).", reachable=True) from exc
            raise CloudflareWorkerError(f"Streamiov AI Worker request failed (HTTP {status}).", reachable=True) from exc
        except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            raise CloudflareWorkerError(f"Streamiov AI Worker request failed: {type(exc).__name__}.") from exc
        if not isinstance(result, dict):
            raise CloudflareWorkerError("Streamiov AI Worker response must be a JSON object.")
        if "error" in result:
            error = result["error"]
            code = error.get("code", "worker_error") if isinstance(error, dict) else "worker_error"
            if code == "daily_ai_limit_reached":
                raise CloudflareWorkerError("Cloudflare Workers AI daily free allocation is exhausted (429).")
            raise CloudflareWorkerError("Streamiov AI Worker reported an inference error.")
        return result


def provider_from_env() -> CloudflareWorkersAIProvider:
    model = os.environ.get("STREAMIOV_MODEL", DEFAULT_MODEL)
    base_url = os.environ.get("STREAMIOV_MODEL_URL", "")
    token = os.environ.get("STREAMIOV_AI_WORKER_TOKEN", "")
    return CloudflareWorkersAIProvider(model=model, base_url=base_url, token=token)
