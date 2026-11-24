import json
import unittest
from unittest.mock import patch

from ai.providers.local_http import ProviderError, provider_from_env
from ai.providers.self_hosted import SelfHostedOpenAIProvider, _endpoint_url


class FakeResponse:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, size=-1):
        return self.payload[:size]


class SelfHostedProviderTests(unittest.TestCase):
    TOKEN = "streamiov-self-hosted-test-token-1234567890"

    def provider(self):
        return SelfHostedOpenAIProvider("qwen2.5-coder:7b", "https://model.example.com", self.TOKEN)

    def test_requires_https_named_host_and_no_url_credentials(self):
        for url in (
            "http://model.example.com",
            "https://localhost",
            "https://user:pass@model.example.com",
            "https://model.example.com:8443",
            "https://model.example.com/path?token=secret",
            "https://127.0.0.1",
            "https://192.168.1.10",
            "https://model.example.com/path",
        ):
            with self.subTest(url=url), self.assertRaises(ProviderError):
                _endpoint_url(url)

    def test_requires_long_bearer_token(self):
        with self.assertRaises(ProviderError):
            SelfHostedOpenAIProvider("model", "https://model.example.com", "short")

    def test_sends_authenticated_chat_request_and_parses_reply(self):
        response = {"choices": [{"message": {"content": "Core model ready"}}]}
        with patch("ai.providers.self_hosted.urlopen", return_value=FakeResponse(response)) as opened:
            reply = self.provider().generate(system="System", messages=[{"role": "user", "content": "Hello"}])
        request = opened.call_args.args[0]
        self.assertEqual(request.get_header("Authorization"), f"Bearer {self.TOKEN}")
        self.assertEqual(request.full_url, "https://model.example.com/v1/chat/completions")
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(payload["model"], "qwen2.5-coder:7b")
        self.assertEqual(reply.content, "Core model ready")
        self.assertEqual(reply.provider, "self-hosted-openai-compatible")

    def test_health_check_reports_configured_model(self):
        response = {"data": [{"id": "other"}, {"id": "qwen2.5-coder:7b"}]}
        with patch("ai.providers.self_hosted.urlopen", return_value=FakeResponse(response)):
            status = self.provider().check_ready()
        self.assertTrue(status["ready"])
        self.assertEqual(status["models_count"], 2)

    def test_health_check_reports_model_missing(self):
        with patch("ai.providers.self_hosted.urlopen", return_value=FakeResponse({"data": []})):
            status = self.provider().check_ready()
        self.assertFalse(status["ready"])
        self.assertTrue(status["reachable"])

    def test_http_errors_do_not_expose_remote_body_or_token(self):
        from urllib.error import HTTPError
        error = HTTPError("https://model.example.com", 401, "Unauthorized", {}, None)
        with patch("ai.providers.self_hosted.urlopen", side_effect=error):
            with self.assertRaises(ProviderError) as caught:
                self.provider().generate(system="", messages=[])
        self.assertIn("HTTP 401", str(caught.exception))
        self.assertNotIn(self.TOKEN, str(caught.exception))

    def test_provider_chain_can_select_self_hosted_before_existing_worker(self):
        with patch.dict("os.environ", {
            "STREAMIOV_MODEL_PROVIDERS": "self-hosted-openai-compatible,cloudflare-workers-ai",
            "STREAMIOV_SELF_HOSTED_MODEL": "qwen2.5-coder:7b",
            "STREAMIOV_SELF_HOSTED_MODEL_URL": "https://model.example.com",
            "STREAMIOV_SELF_HOSTED_MODEL_TOKEN": self.TOKEN,
            "STREAMIOV_MODEL_URL": "https://streamiov-ai.example.workers.dev",
            "STREAMIOV_AI_WORKER_TOKEN": self.TOKEN,
        }, clear=True):
            router = provider_from_env()
        self.assertEqual([name for name, _ in router.providers], [
            "self-hosted-openai-compatible", "cloudflare-workers-ai"
        ])
        self.assertIsInstance(router.providers[0][1], SelfHostedOpenAIProvider)


if __name__ == "__main__":
    unittest.main()
