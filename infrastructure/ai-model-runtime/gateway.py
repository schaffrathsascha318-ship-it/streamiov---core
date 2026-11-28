"""Small bearer-authenticated OpenAI-compatible gateway for a private Ollama service.

Only the gateway port is published by compose. Ollama remains on the private
container network. Request bodies and credentials are never logged.
"""
from __future__ import annotations

import hmac
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MAX_BODY = 64 * 1024
MAX_MESSAGES = 24
MAX_MESSAGE_CHARS = 32_000
MAX_TOTAL_CHARS = 48_000


def configuration():
    token = os.environ.get("STREAMIOV_MODEL_GATEWAY_TOKEN", "")
    if len(token) < 32 or token.lower().startswith(("replace", "change_me", "changeme")):
        raise RuntimeError("STREAMIOV_MODEL_GATEWAY_TOKEN must be a unique random secret of at least 32 characters.")
    model = os.environ.get("STREAMIOV_OLLAMA_MODEL", "qwen2.5-coder:7b").strip()
    if not model:
        raise RuntimeError("STREAMIOV_OLLAMA_MODEL must not be empty.")
    raw = os.environ.get("OLLAMA_BASE_URL", "http://ollama:11434")
    parsed = urllib.parse.urlparse(raw)
    if parsed.scheme != "http" or parsed.hostname not in {"ollama", "127.0.0.1", "localhost"} or not parsed.port or parsed.path or parsed.query or parsed.fragment or parsed.username or parsed.password:
        raise RuntimeError("OLLAMA_BASE_URL must be a private Ollama service URL.")
    return token, model, raw.rstrip("/")


TOKEN, MODEL, OLLAMA_URL = configuration()
request_lock = threading.BoundedSemaphore(int(os.environ.get("STREAMIOV_MODEL_MAX_CONCURRENCY", "2")))


def json_response(handler, data, status=200):
    raw = json.dumps(data, separators=(",", ":")).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.send_header("Content-Length", str(len(raw)))
    handler.end_headers()
    handler.wfile.write(raw)


def ollama_request(path, payload=None):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        OLLAMA_URL + path,
        data=data,
        headers={"Accept": "application/json", **({"Content-Type": "application/json"} if data else {})},
        method="POST" if data else "GET",
    )
    with urllib.request.urlopen(request, timeout=180 if data else 8) as response:
        result = json.loads(response.read(MAX_BODY + 1).decode("utf-8"))
    if not isinstance(result, dict):
        raise ValueError("invalid upstream response")
    return result


class Handler(BaseHTTPRequestHandler):
    server_version = "StreamiovModelGateway"
    sys_version = ""

    def log_message(self, _format, *_args):
        # Do not log URLs, prompts, response bodies, tokens, or user content.
        return

    def authorized(self):
        supplied = self.headers.get("Authorization", "")
        prefix = "Bearer "
        return supplied.startswith(prefix) and hmac.compare_digest(supplied[len(prefix):], TOKEN)

    def do_GET(self):
        if self.path not in ("/health", "/v1/models"):
            return json_response(self, {"error": {"code": "not_found"}}, 404)
        if not self.authorized():
            return json_response(self, {"error": {"code": "unauthorized"}}, 401)
        try:
            tags = ollama_request("/api/tags")
            models = tags.get("models", [])
            if not isinstance(models, list):
                raise ValueError("invalid model list")
            available = any(isinstance(item, dict) and item.get("name") == MODEL for item in models)
            if self.path == "/health":
                return json_response(self, {
                    "ok": available,
                    "service": "streamiov-self-hosted-model",
                    "model": MODEL,
                    "model_available": available,
                }, 200 if available else 503)
            return json_response(self, {
                "object": "list",
                "data": [{"id": item.get("name"), "object": "model"} for item in models if isinstance(item, dict) and isinstance(item.get("name"), str)],
            })
        except (OSError, ValueError, urllib.error.URLError, json.JSONDecodeError):
            return json_response(self, {"error": {"code": "model_runtime_unavailable"}}, 503)

    def do_POST(self):
        if self.path != "/v1/chat/completions":
            return json_response(self, {"error": {"code": "not_found"}}, 404)
        if not self.authorized():
            return json_response(self, {"error": {"code": "unauthorized"}}, 401)
        try:
            size = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return json_response(self, {"error": {"code": "invalid_content_length"}}, 400)
        if size < 2 or size > MAX_BODY:
            return json_response(self, {"error": {"code": "invalid_body_size"}}, 413)
        try:
            payload = json.loads(self.rfile.read(size).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return json_response(self, {"error": {"code": "invalid_json"}}, 400)
        if not isinstance(payload, dict) or payload.get("model") != MODEL or payload.get("stream") is True:
            return json_response(self, {"error": {"code": "invalid_model_or_stream_mode"}}, 400)
        response_format = payload.get("response_format")
        if response_format is not None and (
            not isinstance(response_format, dict) or response_format.get("type") != "json_object"
        ):
            return json_response(self, {"error": {"code": "unsupported_response_format"}}, 400)
        messages = payload.get("messages")
        if not isinstance(messages, list) or not 1 <= len(messages) <= MAX_MESSAGES:
            return json_response(self, {"error": {"code": "invalid_messages"}}, 400)
        total = 0
        for item in messages:
            if not isinstance(item, dict) or item.get("role") not in {"system", "user", "assistant"} or not isinstance(item.get("content"), str):
                return json_response(self, {"error": {"code": "invalid_message"}}, 400)
            if len(item["content"]) > MAX_MESSAGE_CHARS:
                return json_response(self, {"error": {"code": "message_too_large"}}, 413)
            total += len(item["content"])
        if total > MAX_TOTAL_CHARS:
            return json_response(self, {"error": {"code": "prompt_too_large"}}, 413)
        if not request_lock.acquire(blocking=False):
            return json_response(self, {"error": {"code": "runtime_busy"}}, 429)
        try:
            ollama_payload = {
                "model": MODEL,
                "stream": False,
                "messages": messages,
                "options": {"temperature": 0.1},
            }
            if response_format is not None:
                ollama_payload["format"] = "json"
            result = ollama_request("/api/chat", ollama_payload)
            content = result.get("message", {}).get("content")
            if not isinstance(content, str) or not content.strip():
                raise ValueError("invalid model response")
            return json_response(self, {
                "id": "streamiov-" + str(int(time.time() * 1000)),
                "object": "chat.completion",
                "created": int(time.time()),
                "model": MODEL,
                "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
            })
        except (OSError, ValueError, urllib.error.URLError, json.JSONDecodeError):
            return json_response(self, {"error": {"code": "model_runtime_unavailable"}}, 503)
        finally:
            request_lock.release()


if __name__ == "__main__":
    server = ThreadingHTTPServer(("0.0.0.0", int(os.environ.get("PORT", "8080"))), Handler)
    server.serve_forever()
