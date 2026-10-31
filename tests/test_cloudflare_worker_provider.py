import io
import json
import os
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from ai.providers.cloudflare_worker import (
    CloudflareWorkerError,
    CloudflareWorkersAIProvider,
    DEFAULT_MODEL,
    _worker_url,
)
from ai.providers.local_http import provider_from_env


TOKEN = "streamiov-test-token-with-more-than-32-characters"
WORKER_URL = "https://streamiov-ai.example.workers.dev"


class FakeResponse:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode("utf-8")
    def __enter__(self):
        return self
    def __exit__(self, *_args):
        return False
    def read(self):
        return self.payload


class CloudflareWorkerProviderTests(unittest.TestCase):
    def provider(self):
        return CloudflareWorkersAIProvider(DEFAULT_MODEL, WORKER_URL, TOKEN)

    def test_accepts_only_https_workers_dev_urls(self):
        self.assertEqual(_worker_url(WORKER_URL + "/"), WORKER_URL)
        for url in (
            "http://streamiov-ai.example.workers.dev",
            "https://example.com",
            "https://user:pass@streamiov-ai.example.workers.dev",
            "https://streamiov-ai.example.workers.dev?token=secret",
            "https://streamiov-ai.example.workers.dev:8443",
            "https://streamiov-ai.example.workers.dev/path",
        ):
            with self.subTest(url=url), self.assertRaises(CloudflareWorkerError):
                _worker_url(url)

    def test_requires_token_and_pinned_model(self):
        with self.assertRaises(CloudflareWorkerError):
            CloudflareWorkersAIProvider(DEFAULT_MODEL, WORKER_URL, "short")
        with self.assertRaises(CloudflareWorkerError):
            CloudflareWorkersAIProvider("@cf/other/model", WORKER_URL, TOKEN)

    def test_generate_sends_authenticated_openai_compatible_request(self):
        payload = {"choices": [{"message": {"content": '{"final":"cloud model ready"}'}}]}
        with patch("ai.providers.cloudflare_worker.urlopen", return_value=FakeResponse(payload)) as mocked:
            reply = self.provider().generate(
                system="Return JSON only",
                messages=[{"role": "user", "content": "Test"}],
            )
        self.assertEqual(reply.content, '{"final":"cloud model ready"}')
        self.assertEqual(reply.provider, "cloudflare-workers-ai")
        request = mocked.call_args.args[0]
        self.assertEqual(request.full_url, WORKER_URL + "/v1/chat/completions")
        self.assertEqual(request.headers["Authorization"], "Bearer " + TOKEN)
        sent = json.loads(request.data.decode("utf-8"))
        self.assertEqual(sent["model"], DEFAULT_MODEL)
        self.assertEqual(sent["messages"][0]["role"], "system")

    def test_doctor_uses_authenticated_health_endpoint(self):
        with patch(
            "ai.providers.cloudflare_worker.urlopen",
            return_value=FakeResponse({"ok": True, "model": DEFAULT_MODEL})
        ) as mocked:
            status = self.provider().check_ready()
        self.assertTrue(status["reachable"])
        self.assertTrue(status["model_available"])
        self.assertTrue(status["ready"])
        request = mocked.call_args.args[0]
        self.assertEqual(request.full_url, WORKER_URL + "/health")
        self.assertEqual(request.headers["Authorization"], "Bearer " + TOKEN)

    def test_doctor_distinguishes_bad_token_from_unreachable_worker(self):
        error = HTTPError(WORKER_URL + "/health", 401, "Unauthorized", {}, io.BytesIO(b""))
        with patch("ai.providers.cloudflare_worker.urlopen", side_effect=error):
            status = self.provider().check_ready()
        self.assertTrue(status["reachable"])
        self.assertFalse(status["ready"])

    def test_quota_exhaustion_never_falls_back_to_another_provider(self):
        error = HTTPError(WORKER_URL + "/v1/chat/completions", 429, "Too Many Requests", {}, io.BytesIO(b""))
        with patch("ai.providers.cloudflare_worker.urlopen", side_effect=error):
            with self.assertRaisesRegex(CloudflareWorkerError, "daily free allocation"):
                self.provider().generate(system="System", messages=[])

    def test_environment_selects_cloudflare_worker_without_changing_local_defaults(self):
        with patch.dict(os.environ, {
            "STREAMIOV_MODEL_PROVIDER": "cloudflare-workers-ai",
            "STREAMIOV_MODEL_URL": WORKER_URL,
            "STREAMIOV_AI_WORKER_TOKEN": TOKEN,
        }, clear=True):
            provider = provider_from_env()
        self.assertIsInstance(provider, CloudflareWorkersAIProvider)
        self.assertEqual(provider.model, DEFAULT_MODEL)


if __name__ == "__main__":
    unittest.main()
