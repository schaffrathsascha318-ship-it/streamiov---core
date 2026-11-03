import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "verify-cloudflare-config.py"


def load_verifier():
    spec = importlib.util.spec_from_file_location("verify_cloudflare_config", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class CloudflareConfigTests(unittest.TestCase):
    def test_checked_in_cloudflare_configs_are_consistent(self):
        result = load_verifier().verify()
        self.assertTrue(result["ok"], "\n".join(result["errors"]))
        self.assertGreaterEqual(len(result["checks"]), 5)

    def test_jsonc_parser_preserves_urls_inside_strings(self):
        verifier = load_verifier()
        parsed = verifier.strip_jsonc_comments(
            '{\n  // comment\n  "url": "https://example.test/a//b",\n  /* block */\n  "ok": true\n}\n'
        )
        self.assertIn('"https://example.test/a//b"', parsed)
        self.assertNotIn("comment", parsed)
        self.assertNotIn("block", parsed)

    def test_verifier_rejects_secret_like_configuration(self):
        verifier = load_verifier()
        self.assertTrue(verifier._contains_secret_like_key({"vars": {"api_token": "x"}}))
        self.assertFalse(verifier._contains_secret_like_key({"assets": {"directory": "./public"}}))


if __name__ == "__main__":
    unittest.main()
