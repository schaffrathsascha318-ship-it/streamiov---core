from __future__ import annotations

import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "setup-studio-crostini.sh"
README = ROOT / "README.md"


class StudioCrostiniSetupTests(unittest.TestCase):
    def test_setup_script_has_valid_bash_syntax(self):
        result = subprocess.run(
            ["bash", "-n", str(SCRIPT)],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_setup_checks_runtime_and_stream_dependencies_before_launch(self):
        source = SCRIPT.read_text(encoding="utf-8")
        for required in (
            "22.12",
            "python3",
            "npm ci",
            "npm run test:engine",
            "libx264",
            "aac",
            "rtmp",
            "exec npm start",
        ):
            with self.subTest(required=required):
                self.assertIn(required, source)

    def test_setup_does_not_touch_cloud_or_production_configuration(self):
        source = SCRIPT.read_text(encoding="utf-8")
        for forbidden in ("wrangler deploy", "cloudflare deploy", "STREAMIOV_API_TOKEN", "r2"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden.lower(), source.lower())

    def test_readme_documents_the_crostini_first_launch(self):
        source = README.read_text(encoding="utf-8")
        self.assertIn("bash scripts/setup-studio-crostini.sh", source)
        self.assertIn("does not prove camera/audio hardware works", source)


if __name__ == "__main__":
    unittest.main()
