import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "release-signing.mjs"
NODE = shutil.which("node")


@unittest.skipUnless(NODE, "node is required for the signing tool")
class ReleaseSigningTests(unittest.TestCase):
    def run_tool(self, *args, check=None):
        result = subprocess.run(
            [NODE, str(SCRIPT), *[str(arg) for arg in args]],
            capture_output=True,
            text=True,
            cwd=ROOT,
            timeout=120,
        )
        if check is not None:
            self.assertEqual(result.returncode, check, result.stdout + result.stderr)
        return result

    def test_keygen_sign_verify_and_tamper_detection(self):
        with tempfile.TemporaryDirectory() as tmp:
            key = Path(tmp) / "release.key"
            pub = Path(tmp) / "release.pub"
            payload = Path(tmp) / "payload.txt"
            payload.write_text("streamiov release\n", encoding="utf-8")

            result = self.run_tool("keygen", "--key", key, "--pub", pub, check=0)
            info = json.loads(result.stdout)
            self.assertEqual(len(info["fingerprint"]), 64)
            self.assertTrue(key.is_file())
            self.assertTrue(pub.is_file())
            self.assertEqual(key.stat().st_mode & 0o777, 0o600)
            self.assertIn("BEGIN PUBLIC KEY", pub.read_text(encoding="utf-8"))

            for _ in range(2):
                self.run_tool("sign", payload, "--key", key, check=0)
            self.assertTrue(Path(f"{payload}.sig").is_file())
            self.run_tool("verify", payload, "--pub", pub, check=0)

            payload.write_text("tampered\n", encoding="utf-8")
            tampered = self.run_tool("verify", payload, "--pub", pub)
            self.assertNotEqual(tampered.returncode, 0)
            self.assertIn("FEHLER", tampered.stdout)

    def test_keygen_refuses_to_write_a_private_key_inside_the_repository(self):
        target = ROOT / "release-signing-test.key"
        self.assertFalse(target.exists())
        result = self.run_tool("keygen", "--key", target, "--pub", Path(tempfile.gettempdir()) / "unused.pub")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Repository", result.stderr)
        self.assertFalse(target.exists())

    def test_verify_release_checks_signatures_checksums_and_parts(self):
        with tempfile.TemporaryDirectory() as tmp:
            downloads = Path(tmp) / "downloads"
            shutil.copytree(ROOT / "dist/streamiov-homepage-worker/public/downloads", downloads)
            key = Path(tmp) / "release.key"
            pub = Path(tmp) / "release.pub"

            self.run_tool("keygen", "--key", key, "--pub", pub, check=0)
            self.run_tool("sign-release", "--key", key, "--pub", pub, "--dir", downloads, check=0)
            self.assertTrue((downloads / "SHA256SUMS.txt.sig").is_file())

            result = self.run_tool("verify-release", "--pub", pub, "--dir", downloads, check=0)
            report = json.loads(result.stdout)
            self.assertTrue(report["ok"])
            checks = {item["check"] for item in report["checks"]}
            self.assertIn("signature:SHA256SUMS.txt", checks)
            self.assertIn("assembled-archive", checks)

            part = downloads / "streamiov-studio-part-00.bin"
            part.write_bytes(part.read_bytes() + b"tampered")
            broken = self.run_tool("verify-release", "--pub", pub, "--dir", downloads)
            self.assertNotEqual(broken.returncode, 0)
            self.assertFalse(json.loads(broken.stdout)["ok"])

    def test_checked_in_signatures_verify_with_the_published_key(self):
        self.run_tool("verify-release", check=0)


if __name__ == "__main__":
    unittest.main()
