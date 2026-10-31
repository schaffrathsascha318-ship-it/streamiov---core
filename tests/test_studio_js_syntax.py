"""Run Node's parser against the Electron entry points and inline Regie scripts."""
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
STUDIO = ROOT / "dist" / "streamiov-studio-app"


@unittest.skipUnless(shutil.which("node"), "Node.js is required for JavaScript syntax checks")
class StudioJavaScriptSyntaxTests(unittest.TestCase):
    def test_electron_main_and_preload_parse(self):
        for filename in ("main.js", "preload.js"):
            with self.subTest(filename=filename):
                result = subprocess.run(
                    ["node", "--check", str(STUDIO / filename)],
                    capture_output=True,
                    text=True,
                    timeout=20,
                )
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_inline_regie_scripts_parse(self):
        html = (STUDIO / "regie-v2.html").read_text(encoding="utf-8")
        scripts = re.findall(r"<script\\b[^>]*>(.*?)</script\\s*>", html, flags=re.IGNORECASE | re.DOTALL)
        self.assertTrue(scripts, "No inline Regie scripts found")
        checked = 0
        with tempfile.TemporaryDirectory() as temp_dir:
            for index, script in enumerate(scripts):
                if not script.strip():
                    continue
                path = Path(temp_dir) / f"regie-inline-{index}.js"
                path.write_text(script, encoding="utf-8")
                result = subprocess.run(
                    ["node", "--check", str(path)],
                    capture_output=True,
                    text=True,
                    timeout=20,
                )
                self.assertEqual(result.returncode, 0, f"Inline script {index}: {result.stderr}")
                checked += 1
        self.assertGreater(checked, 0, "No inline JavaScript was checked")


if __name__ == "__main__":
    unittest.main()
