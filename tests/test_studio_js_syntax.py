"""Run Node's parser against the Electron entry points and inline Regie scripts."""
from pathlib import Path
import hashlib
import io
import re
import shutil
import subprocess
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
STUDIO = ROOT / "dist" / "streamiov-studio-app"
HOMEPAGE = ROOT / "dist" / "streamiov-homepage-worker" / "public" / "download"
DOWNLOADS = ROOT / "dist" / "streamiov-homepage-worker" / "public" / "downloads"


@unittest.skipUnless(shutil.which("node"), "Node.js is required for JavaScript syntax checks")
class StudioJavaScriptSyntaxTests(unittest.TestCase):
    def test_electron_main_and_preload_parse(self):
        for filename in ("main.js", "preload.js", "media-pipeline.js",
                         "engine/privacy-shield.js", "engine/scene-engine.js"):
            with self.subTest(filename=filename):
                result = subprocess.run(
                    ["node", "--check", str(STUDIO / filename)],
                    capture_output=True,
                    text=True,
                    timeout=20,
                )
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_account_page_inline_scripts_parse(self):
        account = ROOT / "dist" / "streamiov-homepage-worker" / "public" / "account" / "index.html"
        html = account.read_text(encoding="utf-8")
        scripts = re.findall(r"<script[^>]*>(.*?)</script>", html, flags=re.IGNORECASE | re.DOTALL)
        self.assertTrue(scripts, "No account UI script found")
        with tempfile.TemporaryDirectory() as temp_dir:
            for index, script in enumerate(scripts):
                if not script.strip():
                    continue
                path = Path(temp_dir) / f"account-inline-{index}.js"
                path.write_text(script, encoding="utf-8")
                result = subprocess.run(
                    ["node", "--check", str(path)],
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
        names = re.findall(r'name: "(streamiov-studio-part-\d{2}\.bin)"', script)
        sizes = [int(value) for value in re.findall(r"size: (\d+)", script)]
        hashes = re.findall(r'sha256: "([0-9a-f]{64})"', script)
        self.assertEqual(len(names), 7)
        self.assertEqual(len(sizes), 7)
        self.assertEqual(len(hashes), 7)
        if not (DOWNLOADS / names[0]).is_file():
            self.skipTest("download parts are release artifacts and are not part of the source tree")

        assembled = b""
        actual_sizes = []
        for name, size, expected_hash in zip(names, sizes, hashes):
            with self.subTest(part=name):
                path = DOWNLOADS / name
                self.assertTrue(path.is_file(), f"missing download part: {name}")
                payload = path.read_bytes()
                actual_sizes.append(len(payload))
                self.assertEqual(len(payload), size)
                self.assertEqual(hashlib.sha256(payload).hexdigest(), expected_hash)
                assembled += payload
        self.assertEqual(sizes, actual_sizes, "combine.js sizes must match the published parts")

        checksums = (DOWNLOADS / "SHA256SUMS.txt").read_text(encoding="utf-8")
        expected_archive = re.search(
            r"^# assembled archive: ([0-9a-f]{64})", checksums, flags=re.M
        )
        self.assertIsNotNone(expected_archive)
        self.assertEqual(hashlib.sha256(assembled).hexdigest(), expected_archive.group(1))
        self.assertIn(f'"{expected_archive.group(1)}"', script)
        with zipfile.ZipFile(io.BytesIO(assembled)) as archive:
            names_in_zip = set(archive.namelist())
        self.assertIn("dist/streamiov-studio-app/regie-v2.html", names_in_zip)
        self.assertIn("dist/streamiov-studio-app/main.js", names_in_zip)
        self.assertIn("scripts/build-source-snapshot.py", names_in_zip)
        self.assertFalse(any("/release/" in name for name in names_in_zip))
        self.assertFalse(any(name.endswith(".env") for name in names_in_zip))

        self.assertIn("partBytes !== part.size", script)
        self.assertIn("downloaded !== totalSize", script)
        self.assertIn("isZipSignature(signature)", script)
        self.assertIn("crypto.subtle.digest", script)
        self.assertIn("SHA-256-Prüfsumme", script)
        self.assertIn("await writable.abort()", script)

    def test_download_page_documents_the_source_snapshot_and_checksums(self):
        html = (HOMEPAGE / "index.html").read_text(encoding="utf-8")
        checksums = (DOWNLOADS / "SHA256SUMS.txt").read_text(encoding="utf-8")
        sizes = [int(value) for value in re.findall(r"size: (\d+)", (HOMEPAGE / "combine.js").read_text(encoding="utf-8"))]
        archive_hash = re.search(r"^# assembled archive: ([0-9a-f]{64})", checksums, flags=re.M)
        self.assertIsNotNone(archive_hash)
        total = f"{sum(sizes):,}".replace(",", ".")
        self.assertIn("Quellcode-Snapshot", html)
        self.assertIn("kein Installer", html)
        self.assertIn(f"{total} Bytes", html)
        self.assertIn(archive_hash.group(1), html)
        self.assertIn('href="/downloads/SHA256SUMS.txt"', html)
        self.assertIn("inzwischen zusätzlich in Studio 1.0.1 enthalten", html)
        self.assertIn("Release-Signatur", html)
        self.assertIn("/downloads/STREAMIOV-RELEASE-KEY.pub", html)
        self.assertIn("/downloads/SHA256SUMS.txt.sig", html)
        self.assertIn("5aba9e30b37a060505470483673bf6b44b66e12bf050edb4fd57415f29f7d2bc", html)

    def test_promo_page_uses_real_media_and_states_the_limits(self):
        public = ROOT / "dist" / "streamiov-homepage-worker" / "public"
        html = (public / "promo" / "index.html").read_text(encoding="utf-8")
        self.assertIn("StreamioV Studio 1.0.1", html)
        self.assertIn("Ctrl+Shift+P", html)
        self.assertIn("stoppt weder den Encoder noch eine laufende Aufnahme", html)
        self.assertIn("keine Plattform-Privatsphäre", html)
        self.assertIn("regie-schutzregie-demo.webm", html)
        self.assertIn("data-copy", html)
        for asset in (
            "homepage-desktop.png",
            "download-hub.png",
            "regie-live.png",
            "regie-shield-desktop.png",
            "regie-shield-mobile.png",
            "regie-schutzregie-demo.webm",
        ):
            with self.subTest(asset=asset):
                path = public / "promo" / "media" / asset
                self.assertTrue(path.is_file(), f"missing real promo asset: {asset}")
                self.assertGreater(path.stat().st_size, 10_000)

    def test_source_snapshot_builder_is_reproducible_and_excludes_private_artifacts(self):
        script = (ROOT / "scripts" / "build-source-snapshot.py").read_text(encoding="utf-8")
        self.assertIn('["git", "ls-files", "-z"]', script)
        self.assertIn("PART_COUNT = 7", script)
        for excluded in ("data/db/", "promo/media/", "release/", ".env", ".wrangler"):
            self.assertIn(excluded, script)
        self.assertIn("def update_download_combiner", script)
        self.assertIn("def update_download_page", script)
        self.assertIn("SHA256SUMS.txt", script)
        # Fixed zip timestamps make repeated builds byte-identical.
        self.assertIn("ZIP_TIMESTAMP", script)
        self.assertIn("zipfile.ZipInfo", script)
        self.assertIn('"dist/streamiov-homepage-worker/public/download/"', script)
        # Manifests are re-signed after every build when the owner key exists.
        self.assertIn("def sign_downloads", script)
        self.assertIn("sign-release", script)
        self.assertIn("SIGNING_KEY", script)

if __name__ == "__main__":
    unittest.main()
