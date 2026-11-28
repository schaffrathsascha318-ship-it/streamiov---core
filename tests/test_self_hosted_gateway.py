import importlib.util
from pathlib import Path
import sys
import json
import os
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen


class SelfHostedGatewayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.env_patch = patch.dict(os.environ, {
            "STREAMIOV_MODEL_GATEWAY_TOKEN": "streamiov-gateway-test-token-1234567890",
            "STREAMIOV_OLLAMA_MODEL": "qwen2.5-coder:7b",
            "OLLAMA_BASE_URL": "http://ollama:11434",
            "STREAMIOV_MODEL_MAX_CONCURRENCY": "2",
        })
        cls.env_patch.start()
        gateway_path = Path(__file__).resolve().parents[1] / "infrastructure" / "ai-model-runtime" / "gateway.py"
        spec = importlib.util.spec_from_file_location("streamiov_model_gateway_test", gateway_path)
        cls.gateway = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = cls.gateway
        spec.loader.exec_module(cls.gateway)
        cls.server = cls.gateway.ThreadingHTTPServer(("127.0.0.1", 0), cls.gateway.Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"
        cls.token = "streamiov-gateway-test-token-1234567890"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)
        cls.env_patch.stop()

    def request(self, path, *, method="GET", payload=None, token=None):
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {}
        if token is not None:
            headers["Authorization"] = f"Bearer {token}"
        if data is not None:
            headers["Content-Type"] = "application/json"
        request = Request(self.base + path, data=data, headers=headers, method=method)
        try:
            with urlopen(request, timeout=3) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    def test_gateway_rejects_placeholder_token_at_startup(self):
        with patch.dict(os.environ, {
            "STREAMIOV_MODEL_GATEWAY_TOKEN": "replace-with-a-random-secret-at-least-32-characters"
        }):
            with self.assertRaisesRegex(RuntimeError, "unique random secret"):
                self.gateway.configuration()

    def test_health_requires_bearer_token(self):
        status, body = self.request("/health")
        self.assertEqual(status, 401)
        self.assertEqual(body["error"]["code"], "unauthorized")

    def test_health_reports_model_ready_only_when_ollama_lists_it(self):
        with patch.object(self.gateway, "ollama_request", return_value={
            "models": [{"name": "qwen2.5-coder:7b"}]
        }):
            status, body = self.request("/health", token=self.token)
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(body["model"], "qwen2.5-coder:7b")

    def test_models_endpoint_exposes_only_model_metadata(self):
        with patch.object(self.gateway, "ollama_request", return_value={
            "models": [{"name": "qwen2.5-coder:7b", "size": 123456}]
        }):
            status, body = self.request("/v1/models", token=self.token)
        self.assertEqual(status, 200)
        self.assertEqual(body["data"], [{"id": "qwen2.5-coder:7b", "object": "model"}])

    def test_chat_translates_openai_request_to_ollama_and_back(self):
        with patch.object(self.gateway, "ollama_request", return_value={
            "message": {"content": "Streamiov self-hosted inference works"}
        }) as upstream:
            status, body = self.request(
                "/v1/chat/completions",
                method="POST",
                token=self.token,
                payload={
                    "model": "qwen2.5-coder:7b",
                    "stream": False,
                    "messages": [{"role": "user", "content": "Hello"}],
                    "response_format": {"type": "json_object"},
                },
            )
        self.assertEqual(status, 200)
        self.assertEqual(body["choices"][0]["message"]["content"], "Streamiov self-hosted inference works")
        self.assertEqual(upstream.call_args.args[0], "/api/chat")
        self.assertEqual(upstream.call_args.args[1]["model"], "qwen2.5-coder:7b")
        self.assertEqual(upstream.call_args.args[1]["format"], "json")

    def test_chat_rejects_unsupported_response_format_before_inference(self):
        with patch.object(self.gateway, "ollama_request") as upstream:
            status, body = self.request(
                "/v1/chat/completions", method="POST", token=self.token,
                payload={
                    "model": "qwen2.5-coder:7b",
                    "messages": [{"role": "user", "content": "hi"}],
                    "response_format": {"type": "json_schema", "schema": {}},
                },
            )
        self.assertEqual(status, 400)
        self.assertEqual(body["error"]["code"], "unsupported_response_format")
        upstream.assert_not_called()

    def test_chat_rejects_wrong_model_and_invalid_roles_before_inference(self):
        with patch.object(self.gateway, "ollama_request") as upstream:
            wrong_model = self.request(
                "/v1/chat/completions", method="POST", token=self.token,
                payload={"model": "other", "messages": [{"role": "user", "content": "hi"}]},
            )
            invalid_role = self.request(
                "/v1/chat/completions", method="POST", token=self.token,
                payload={"model": "qwen2.5-coder:7b", "messages": [{"role": "tool", "content": "hi"}]},
            )
        self.assertEqual(wrong_model[0], 400)
        self.assertEqual(invalid_role[0], 400)
        upstream.assert_not_called()


if __name__ == "__main__":
    unittest.main()
