import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "collect-hardware-report.py"


class HardwareReportTests(unittest.TestCase):
    def run_script(self, *args):
        return subprocess.run(
            [sys.executable, str(SCRIPT), *[str(arg) for arg in args]],
            capture_output=True,
            text=True,
            timeout=120,
        )

    def test_json_report_contains_platform_and_file_hashes(self):
        with tempfile.TemporaryDirectory() as tmp:
            installer = Path(tmp) / "Streamiov.Studio.Setup.test.exe"
            installer.write_bytes(b"streamiov-installer")
            result = self.run_script(installer)
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report["hardware"]["machine"], __import__("platform").machine())
            self.assertEqual(report["files"][0]["sha256"], hashlib.sha256(b"streamiov-installer").hexdigest())
            self.assertEqual(report["files"][0]["bytes"], len(b"streamiov-installer"))
            self.assertIn("note", report)

    def test_markdown_report_is_human_readable(self):
        result = self.run_script("--markdown")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("# STREAMIOV Hardware-Bericht", result.stdout)
        self.assertIn("SHA-256", result.stdout)

    def test_missing_file_fails_cleanly(self):
        result = self.run_script(ROOT / "missing-installer.exe")
        self.assertEqual(result.returncode, 2)
        self.assertIn("Datei fehlt", result.stderr)


if __name__ == "__main__":
    unittest.main()
