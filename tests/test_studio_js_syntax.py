"""Run Node's parser against the Electron entry points and inline Regie scripts."""
from pathlib import Path
import hashlib
import importlib.util
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
                         "engine/privacy-shield.js", "engine/device-capabilities.js",
                         "engine/scene-engine.js", "engine/app-updater.js",
                         "engine/media-asset-store.js", "program-output-preload.js"):
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

    def test_program_output_inline_script_parses(self):
        html = (STUDIO / "program-output.html").read_text(encoding="utf-8")
        scripts = re.findall(r"<script[^>]*>(.*?)</script>", html, flags=re.IGNORECASE | re.DOTALL)
        self.assertEqual(len(scripts), 1)
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "program-output-inline.js"
            path.write_text(scripts[0], encoding="utf-8")
            result = subprocess.run(
                ["node", "--check", str(path)],
                capture_output=True,
                text=True,
                timeout=20,
            )
            self.assertEqual(result.returncode, 0, result.stderr)


class HomepageDownloadPageTests(unittest.TestCase):
    def test_download_page_exposes_combiner_and_all_seven_parts(self):
        html = (HOMEPAGE / "index.html").read_text(encoding="utf-8")
        script = (HOMEPAGE / "combine.js").read_text(encoding="utf-8")
        self.assertIn('<script src="/download/combine.js" defer></script>', html)
        self.assertEqual(html.count("data-studio-download"), 2)
        for element_id in ("source-snapshot-download", "source-snapshot-status",
                           "source-snapshot-progress", "quellcode-download",
                           "quellcode-status", "quellcode-progress"):
            with self.subTest(element_id=element_id):
                self.assertIn(f'id="{element_id}"', html)
        for index in range(7):
            filename = f"streamiov-studio-part-{index:02d}.bin"
            self.assertIn(f'href="/downloads/{filename}"', html)
            self.assertIn(f'name: "{filename}"', script)

    def test_download_page_has_unique_ids_and_wires_both_snapshot_buttons(self):
        html = (HOMEPAGE / "index.html").read_text(encoding="utf-8")
        script = (HOMEPAGE / "combine.js").read_text(encoding="utf-8")
        ids = re.findall(r'\bid="([^"]+)"', html)
        self.assertEqual(sorted({item for item in ids if ids.count(item) > 1}), [])
        self.assertIn('document.querySelectorAll("[data-studio-download]")', script)
        self.assertIn("button.dataset.studioStatus", script)
        self.assertIn("button.dataset.studioProgress", script)
        self.assertNotIn("fünf checksumierte Spiel-Prototypen", html)

    def test_source_snapshot_metadata_update_rewrites_both_download_blocks(self):
        spec = importlib.util.spec_from_file_location(
            "streamiov_source_snapshot", ROOT / "scripts" / "build-source-snapshot.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as directory:
            module.ROOT = Path(directory)
            target = Path(directory) / "dist/streamiov-homepage-worker/public/download/index.html"
            target.parent.mkdir(parents=True)
            target.write_text((HOMEPAGE / "index.html").read_text(encoding="utf-8"), encoding="utf-8")
            digest = "b" * 64
            module.update_download_page([{"bytes": 1234}], digest)
            updated = target.read_text(encoding="utf-8")
        self.assertEqual(updated.count("Gesamtgröße: 1.234 Bytes"), 2)
        self.assertEqual(updated.count(f"<code>{digest}</code>"), 2)

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
        self.assertNotIn("hashUnavailable", script)
        self.assertIn("SHA-256 ist in diesem Browser nicht verfügbar", script)
        self.assertNotIn("Die SHA-256-Prüfung ist in diesem Browser", script)

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
        self.assertIn("inzwischen zusätzlich in Studio 1.0.4 enthalten", html)
        self.assertIn("Release-Signatur", html)
        self.assertIn("/downloads/STREAMIOV-RELEASE-KEY.pub", html)
        self.assertIn("/downloads/SHA256SUMS.txt.sig", html)
        self.assertIn("2c3de4b60d60cf4c7fa19ac3378a504706f79960978dfb610d9660bc10aeb09e", html)

    def test_promo_page_uses_real_media_and_states_the_limits(self):
        public = ROOT / "dist" / "streamiov-homepage-worker" / "public"
        html = (public / "promo" / "index.html").read_text(encoding="utf-8")
        self.assertIn("StreamioV Studio 1.0.4", html)
        self.assertIn("Ctrl+Shift+P", html)
        self.assertIn("Stopp des lokalen Encoders", html)
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

    def test_public_site_has_no_browser_app_or_pwa_product(self):
        public = ROOT / "dist" / "streamiov-homepage-worker" / "public"
        self.assertFalse((public / "app").exists())
        for page in ("index.html", "download/index.html", "promo/index.html", "studio/index.html", "forum/index.html"):
            with self.subTest(page=page):
                markup = (public / page).read_text(encoding="utf-8")
                self.assertNotIn('href="/app/"', markup)
                self.assertNotIn("serviceWorker.register", markup)
        studio = (public / "studio" / "index.html").read_text(encoding="utf-8")
        self.assertIn("/download/#installer", studio)

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

    def test_installer_start_update_and_error_chain_stays_honest(self):
        main = (STUDIO / "main.js").read_text(encoding="utf-8")
        package = (STUDIO / "package.json").read_text(encoding="utf-8")
        html = (HOMEPAGE / "index.html").read_text(encoding="utf-8")
        combiner = (HOMEPAGE / "combine.js").read_text(encoding="utf-8")
        updater = (STUDIO / "engine" / "app-updater.js").read_text(encoding="utf-8")
        for source, text in (("main.js", main), ("package.json", package),
                             ("download/index.html", html), ("download/combine.js", combiner),
                             ("engine/app-updater.js", updater)):
            with self.subTest(source=source):
                self.assertNotIn("electron-updater", text)
                self.assertNotIn("autoUpdater", text)
                self.assertNotIn("latest.yml", text)
        self.assertIn("/downloads/SHA256SUMS.txt.sig", html)
        self.assertIn("Release-Signatur prüfen", html)
        self.assertIn("keine</strong> Windows-/macOS-Code-Signatur", html)
        self.assertIn("isZipSignature(signature)", combiner)
        self.assertIn("await writable.abort()", combiner)

    def test_pinned_update_chain_is_wired_without_renderer_controlled_targets(self):
        main = (STUDIO / "main.js").read_text(encoding="utf-8")
        preload = (STUDIO / "preload.js").read_text(encoding="utf-8")
        regie = (STUDIO / "regie-v2.html").read_text(encoding="utf-8")
        updater = (STUDIO / "engine" / "app-updater.js").read_text(encoding="utf-8")
        generator = (ROOT / "scripts" / "build-studio-update-manifest.mjs").read_text(encoding="utf-8")
        for channel in ("studio:update-status", "studio:update-check", "studio:update-prepare",
                        "studio:update-install", "studio:update-clear-error",
                        "studio:update-open-release"):
            with self.subTest(channel=channel):
                self.assertIn(channel, main)
                self.assertIn(channel, preload)
        self.assertIn("isTrustedStudioSender(event)", main)
        self.assertIn("isUpdateAllowed: () => !liveOutputManager.isActive() && liveStreamState === 'offline'", main)
        self.assertIn("data-tool=\"Update\"", regie)
        self.assertIn("renderUpdateTool", regie)
        self.assertIn("crypto.verify(null", updater)
        self.assertIn("sha256_mismatch", updater)
        self.assertIn("cleanupStaged", updater)
        self.assertIn("releaseAssetUrl", updater)
        self.assertIn("streamiov-studio-update-v1", generator)
        self.assertIn("createPrivateKey", generator)
        self.assertNotIn("ipcRenderer.invoke('studio:update-check',", preload)

    def test_stream_destinations_are_derived_only_from_platform_oauth_credentials(self):
        main = (STUDIO / "main.js").read_text(encoding="utf-8")
        preload = (STUDIO / "preload.js").read_text(encoding="utf-8")
        regie = (STUDIO / "regie-v2.html").read_text(encoding="utf-8")
        self.assertNotIn("payload.destination", main)
        self.assertNotIn("payload.destination", preload)
        self.assertIn("options.platforms", main)
        self.assertIn("resolveOutputCredentials", main)
        self.assertIn("getTwitchOAuth().getStreamCredentials()", main)
        self.assertIn("getTikTokOAuth().getStreamCredentials()", main)
        self.assertIn("normalizeTwitchDestination(credentials)", main)
        self.assertIn("ingest.hostname !== 'live.twitch.tv'", main)
        self.assertIn("platforms: Array.isArray(payload?.platforms)", preload)
        call = re.search(r"startStream\(\{(.*?)\}\);", regie, flags=re.S)
        self.assertIsNotNone(call)
        self.assertNotIn("destination", call.group(1))
        self.assertIn("platforms,", call.group(1))
        self.assertIn("ipcMain.handle('studio:get-stream-status'", main)
        self.assertIn("getStreamStatus: () => ipcRenderer.invoke('studio:get-stream-status')", preload)
        self.assertIn("async function syncStreamState()", regie)
        self.assertIn("if(state?.active)return stopBroadcast(true,true);", regie)
        self.assertNotIn("liveButton.onclick=()=>broadcastRecorder?stopBroadcast():startBroadcast();", regie)

if __name__ == "__main__":
    unittest.main()
