"""Run Node's parser against the Electron entry points and inline Regie scripts."""
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
STUDIO = ROOT / "dist" / "streamiov-studio-app"
HOMEPAGE = ROOT / "dist" / "streamiov-homepage-worker" / "public" / "download"


@unittest.skipUnless(shutil.which("node"), "Node.js is required for JavaScript syntax checks")
class StudioJavaScriptSyntaxTests(unittest.TestCase):
    def test_electron_main_and_preload_parse(self):
        for filename in ("main.js", "preload.js", "media-pipeline.js"):
            with self.subTest(filename=filename):
                result = subprocess.run(
                    ["node", "--check", str(STUDIO / filename)],
                    capture_output=True,
                    text=True,
                    timeout=20,
                )
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_homepage_download_combiner_parses(self):
        script = HOMEPAGE / "combine.js"
        result = subprocess.run(
            ["node", "--check", str(script)],
            capture_output=True,
            text=True,
            timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_inline_regie_scripts_parse(self):
        html = (STUDIO / "regie-v2.html").read_text(encoding="utf-8")
        scripts = re.findall(r"<script[^>]*>(.*?)</script>", html, flags=re.IGNORECASE | re.DOTALL)
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




class HomepageDownloadPageTests(unittest.TestCase):
    def test_download_page_exposes_combiner_and_all_seven_parts(self):
        html = (HOMEPAGE / "index.html").read_text(encoding="utf-8")
        script = (HOMEPAGE / "combine.js").read_text(encoding="utf-8")
        self.assertIn('<script src="/download/combine.js" defer></script>', html)
        self.assertIn('id="studio-one-click"', html)
        self.assertIn('id="studio-status"', html)
        self.assertIn('id="studio-progress"', html)
        for index in range(7):
            filename = f"streamiov-studio-part-{index:02d}.bin"
            self.assertIn(f'href="/downloads/{filename}"', html)
            self.assertIn(f'name: "{filename}"', script)

    def test_download_combiner_uses_exact_part_sizes_and_validates_zip(self):
        script = (HOMEPAGE / "combine.js").read_text(encoding="utf-8")
        sizes = [int(value) for value in re.findall(r"size: (\d+)", script)]
        self.assertEqual(sizes, [20971520] * 6 + [8982160])
        self.assertEqual(sum(sizes), 134811280)
        self.assertIn("partBytes !== part.size", script)
        self.assertIn("downloaded !== totalSize", script)
        self.assertIn("isZipSignature(signature)", script)
        self.assertIn("await writable.abort()", script)

if __name__ == "__main__":
    unittest.main()
