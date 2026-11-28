import hashlib
import importlib.util
import json
import re
import shutil
import subprocess
import tempfile
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

    def test_production_deployment_is_manual_only_and_requires_confirmation(self):
        workflow = (ROOT / ".github" / "workflows" / "cloudflare-deploy.yml").read_text(encoding="utf-8")
        self.assertIn("workflow_dispatch:", workflow)
        self.assertNotRegex(workflow, r"(?m)^  push:")
        self.assertNotRegex(workflow, r"(?m)^  pull_request:")
        for job_name in ("verify", "deploy-homepage", "deploy-ai-worker"):
            match = re.search(rf"(?ms)^  {job_name}:.*?(?=^  [A-Za-z0-9_-]+:|\Z)", workflow)
            self.assertIsNotNone(match, f"missing Cloudflare job: {job_name}")
            block = match.group(0)
            self.assertIn("github.event_name == 'workflow_dispatch'", block)
            self.assertIn("inputs.confirm == true", block)
            if job_name != "verify":
                self.assertIn("needs.verify.result == 'success'", block)

    def test_download_page_accepts_direct_assets_from_streamiov_releases(self):
        verifier = load_verifier()
        markup = """
          <a href="https://github.com/schaffrathsascha318-ship-it/streamiov---core/releases/download/studio-v1.0.2/Streamiov.Studio.Setup.1.0.2-x64.exe">Windows</a>
          <a href="https://github.com/schaffrathsascha318-ship-it/streamiov---core/releases/download/studio-v1.0.2/streamiov-studio_1.0.2_arm64.deb">Linux ARM64</a>
          <a href="https://github.com/schaffrathsascha318-ship-it/streamiov---core/releases/download/studio-v1.0.2/Streamiov.Studio-1.0.2-arm64-unsigned.dmg">macOS ARM64</a>
         """
        self.assertEqual(len(verifier.find_release_download_targets(markup)), 3)
        self.assertEqual(verifier.find_local_download_targets(markup), [])

    def test_download_page_rejects_untrusted_release_hosts_and_tag_pages(self):
        verifier = load_verifier()
        markup = """
          <a href="https://github.com/attacker/other/releases/download/v1/app.exe">bad repo</a>
          <a href="https://github.com/schaffrathsascha318-ship-it/streamiov---core/releases/tag/studio-v1.0.2">tag page</a>
          <a href="https://example.test/releases/download/v1/app.exe">bad host</a>
        """
        self.assertEqual(verifier.find_release_download_targets(markup), [])

    def test_download_page_finds_local_assets(self):
        verifier = load_verifier()
        markup = '<a href="/downloads/streamiov-windows.zip">Windows</a>'
        self.assertEqual(verifier.find_local_download_targets(markup), ["/downloads/streamiov-windows.zip"])

    def test_jsonc_parser_preserves_urls_inside_strings(self):
        verifier = load_verifier()
        parsed = verifier.strip_jsonc_comments(
            '{\n  // comment\n  "url": "https://example.test/a//b",\n  /* block */\n  "ok": true\n}\n'
        )
        self.assertIn('"https://example.test/a//b"', parsed)
        self.assertNotIn("comment", parsed)
        self.assertNotIn("block", parsed)

    def test_r2_policy_rejects_bucket_bindings_and_cli_commands(self):
        verifier = load_verifier()
        self.assertTrue(verifier.find_forbidden_r2_usage('"r2_buckets": [{"binding": "MEDIA"}]'))
        self.assertTrue(verifier.find_forbidden_r2_usage("npx wrangler r2 bucket create media"))
        self.assertTrue(verifier.find_forbidden_r2_usage("env.R2_BUCKET.put(key, value)"))

    def test_r2_policy_allows_unrelated_configuration(self):
        verifier = load_verifier()
        self.assertEqual(verifier.find_forbidden_r2_usage('{"assets": {"directory": "./public"}}'), [])

    def test_verifier_rejects_secret_like_configuration(self):
        verifier = load_verifier()
        self.assertTrue(verifier._contains_secret_like_key({"vars": {"api_token": "x"}}))
        self.assertFalse(verifier._contains_secret_like_key({"assets": {"directory": "./public"}}))

    def test_offline_verifier_checks_release_signatures(self):
        verifier = load_verifier()
        ok, detail = verifier.verify_release_signatures(ROOT / "dist/streamiov-homepage-worker/public/downloads")
        self.assertTrue(ok, detail)

    def test_offline_verifier_checks_hosted_studio_update_manifest(self):
        verifier = load_verifier()
        downloads = ROOT / "dist/streamiov-homepage-worker/public/downloads"
        ok, detail = verifier.verify_studio_update_manifest(downloads)
        self.assertTrue(ok, detail)
        checks = verifier.verify()["checks"]
        self.assertIn("hosted Studio update manifest is signed and lists only published Windows/Linux assets", checks)

    def test_offline_verifier_rejects_a_tampered_studio_update_manifest(self):
        verifier = load_verifier()
        with tempfile.TemporaryDirectory() as tmp:
            downloads = Path(tmp) / "downloads"
            shutil.copytree(ROOT / "dist/streamiov-homepage-worker/public/downloads", downloads)
            manifest = downloads / "studio-update.json"
            data = json.loads(manifest.read_text(encoding="utf-8"))
            data["assets"]["win32-x64"]["filename"] = "malware.exe"
            manifest.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
            ok, _ = verifier.verify_studio_update_manifest(downloads)
            self.assertFalse(ok)

    def test_offline_verifier_rejects_a_manipulated_part_with_rewritten_checksum(self):
        verifier = load_verifier()
        with tempfile.TemporaryDirectory() as tmp:
            downloads = Path(tmp) / "downloads"
            shutil.copytree(ROOT / "dist/streamiov-homepage-worker/public/downloads", downloads)
            part = downloads / "streamiov-studio-part-00.bin"
            part.write_bytes(part.read_bytes() + b"angriff")
            digest = hashlib.sha256(part.read_bytes()).hexdigest()
            sums = downloads / "SHA256SUMS.txt"
            lines = [
                f"{digest}  streamiov-studio-part-00.bin" if line.endswith("  streamiov-studio-part-00.bin") else line
                for line in sums.read_text(encoding="utf-8").splitlines()
            ]
            sums.write_text("\n".join(lines) + "\n", encoding="utf-8")

            ok, detail = verifier.verify_release_signatures(downloads)
            self.assertFalse(ok)
            self.assertIn("signature:SHA256SUMS.txt", detail)

    @unittest.skipUnless(shutil.which("node"), "node is required to generate a test-only key")
    def test_offline_verifier_rejects_an_unknown_trust_anchor(self):
        verifier = load_verifier()
        with tempfile.TemporaryDirectory() as tmp:
            downloads = Path(tmp) / "downloads"
            shutil.copytree(ROOT / "dist/streamiov-homepage-worker/public/downloads", downloads)
            key = Path(tmp) / "test-only.key"
            attacker_pub = Path(tmp) / "test-only.pub"
            subprocess.run(
                [shutil.which("node"), str(ROOT / "scripts/release-signing.mjs"), "keygen",
                 "--key", str(key), "--pub", str(attacker_pub)],
                cwd=ROOT, check=True, capture_output=True, text=True, timeout=60,
            )
            shutil.copyfile(attacker_pub, downloads / "STREAMIOV-RELEASE-KEY.pub")

            ok, detail = verifier.verify_release_signatures(downloads)
            self.assertFalse(ok)
            self.assertIn("key-fingerprint", detail)

    def test_offline_verifier_rejects_missing_game_checksum_manifest(self):
        verifier = load_verifier()
        with tempfile.TemporaryDirectory() as tmp:
            downloads = Path(tmp) / "downloads"
            shutil.copytree(ROOT / "dist/streamiov-homepage-worker/public/downloads", downloads)
            (downloads / "SHA256SUMS-games.txt").unlink()
            (downloads / "SHA256SUMS-games.txt.sig").unlink()
            ok, detail = verifier.verify_release_signatures(downloads)
            self.assertFalse(ok)
            self.assertIn("manifest:SHA256SUMS-games.txt", detail)


if __name__ == "__main__":
    unittest.main()
