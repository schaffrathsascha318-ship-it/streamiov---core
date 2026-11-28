import hashlib
import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "release-signing.mjs"
WORKFLOW = ROOT / ".github" / "workflows" / "studio-build.yml"
UPDATE_NOTES = ROOT / "docs" / "STUDIO_UPDATE_NOTES.md"
DOWNLOAD_PAGE = ROOT / "dist/streamiov-homepage-worker/public/download/index.html"
PROMO_PAGE = ROOT / "dist/streamiov-homepage-worker/public/promo/index.html"
NODE = shutil.which("node")
EXPECTED_FINGERPRINT = "2c3de4b60d60cf4c7fa19ac3378a504706f79960978dfb610d9660bc10aeb09e"


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
            self.run_tool("sign-release", "--key", key, "--pub", pub, "--dir", downloads, "--allow-key-rotation", check=0)
            self.assertTrue((downloads / "SHA256SUMS.txt.sig").is_file())

            result = self.run_tool("verify-release", "--pub", pub, "--dir", downloads, "--allow-key-rotation", check=0)
            report = json.loads(result.stdout)
            self.assertTrue(report["ok"])
            checks = {item["check"] for item in report["checks"]}
            self.assertIn("signature:SHA256SUMS.txt", checks)
            self.assertIn("assembled-archive", checks)

            part = downloads / "streamiov-studio-part-00.bin"
            part.write_bytes(part.read_bytes() + b"tampered")
            broken = self.run_tool("verify-release", "--pub", pub, "--dir", downloads, "--allow-key-rotation")
            self.assertNotEqual(broken.returncode, 0)
            self.assertFalse(json.loads(broken.stdout)["ok"])

    def test_verify_release_rejects_a_manipulated_part_with_a_matching_manifest(self):
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

            result = self.run_tool("verify-release", "--dir", downloads)
            self.assertNotEqual(result.returncode, 0)
            report = json.loads(result.stdout)
            self.assertFalse(report["ok"])
            signature = next(item for item in report["checks"] if item["check"] == "signature:SHA256SUMS.txt")
            self.assertFalse(signature["ok"])

    def test_verify_release_requires_every_checksum_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            downloads = Path(tmp) / "downloads"
            shutil.copytree(ROOT / "dist/streamiov-homepage-worker/public/downloads", downloads)
            (downloads / "SHA256SUMS-games.txt").unlink()
            (downloads / "SHA256SUMS-games.txt.sig").unlink()

            result = self.run_tool("verify-release", "--dir", downloads)
            self.assertNotEqual(result.returncode, 0)
            report = json.loads(result.stdout)
            self.assertFalse(report["ok"])
            missing = next(item for item in report["checks"] if item["check"] == "manifest:SHA256SUMS-games.txt")
            self.assertFalse(missing["ok"])

    def test_verify_release_rejects_an_unpinned_key_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            downloads = Path(tmp) / "downloads"
            shutil.copytree(ROOT / "dist/streamiov-homepage-worker/public/downloads", downloads)
            key = Path(tmp) / "release.key"
            pub = Path(tmp) / "release.pub"
            self.run_tool("keygen", "--key", key, "--pub", pub, check=0)
            self.run_tool("sign-release", "--key", key, "--pub", pub, "--dir", downloads, "--allow-key-rotation", check=0)

            result = self.run_tool("verify-release", "--pub", pub, "--dir", downloads)
            self.assertNotEqual(result.returncode, 0)
            report = json.loads(result.stdout)
            self.assertFalse(report["ok"])
            fingerprint_check = next(item for item in report["checks"] if item["check"] == "key-fingerprint")
            self.assertFalse(fingerprint_check["ok"])
            self.assertEqual(fingerprint_check["expected"], EXPECTED_FINGERPRINT)
            self.assertNotEqual(fingerprint_check["actual"], EXPECTED_FINGERPRINT)

    def test_checked_in_signatures_verify_with_the_published_key(self):
        self.run_tool("verify-release", check=0)

    def test_all_pinned_trust_anchors_are_consistent(self):
        for relative in (
            "scripts/release-signing.mjs",
            "scripts/verify-cloudflare-config.py",
            "tests/test_release_signing.py",
            "dist/streamiov-studio-app/engine/app-updater.test.js",
            "dist/streamiov-homepage-worker/public/download/index.html",
            "docs/STATUS.md",
            "docs/operations/external-verification.md",
        ):
            with self.subTest(file=relative):
                self.assertIn(EXPECTED_FINGERPRINT, (ROOT / relative).read_text(encoding="utf-8"))

        published = (ROOT / "dist/streamiov-homepage-worker/public/downloads/STREAMIOV-RELEASE-KEY.pub").read_text(encoding="utf-8")
        updater = (ROOT / "dist/streamiov-studio-app/engine/app-updater.js").read_text(encoding="utf-8")
        pattern = r"-----BEGIN PUBLIC KEY-----\s*([A-Za-z0-9+/=]+)\s*-----END PUBLIC KEY-----"
        published_body = "".join(re.search(pattern, published, flags=re.S).group(1).split())
        updater_body = "".join(re.search(pattern, updater, flags=re.S).group(1).split())
        self.assertEqual(published_body, updater_body)


class StudioReleaseWorkflowTests(unittest.TestCase):
    def test_workflow_builds_and_attaches_ffmpeg_corresponding_source(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("name: FFmpeg corresponding source bundle", workflow)
        self.assertIn("python scripts/build-ffmpeg-source-bundle.py", workflow)
        self.assertIn("sudo apt-get install -y subversion", workflow)
        self.assertIn("name: streamiov-ffmpeg-source-code", workflow)
        publish = workflow.split("  publish-release:", 1)[1]
        self.assertIn("needs: [build, media-pipeline-smoke, ffmpeg-source]", publish)
        self.assertIn('SOURCE_DIR="artifacts/streamiov-ffmpeg-source-code"', publish)
        self.assertIn("release/ffmpeg-source-bundle.tar.xz", publish)
        self.assertIn("release/FFMPEG-SOURCE-SHA256SUMS.txt", publish)

    def test_workflow_creates_signed_update_manifest(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")
        publish = workflow.split("  publish-release:", 1)[1]
        self.assertIn("scripts/build-studio-update-manifest.mjs", publish)
        self.assertIn("STUDIO_RELEASE_SIGNING_KEY: ${{ secrets.STUDIO_RELEASE_SIGNING_KEY }}", publish)
        self.assertIn("--notes-file docs/STUDIO_UPDATE_NOTES.md", publish)
        self.assertIn("name: streamiov-studio-update-manifest", publish)
        manifest_script = (ROOT / "scripts" / "build-studio-update-manifest.mjs").read_text(encoding="utf-8")
        self.assertIn("target: 'darwin-x64'", manifest_script)
        self.assertIn("target: 'darwin-arm64'", manifest_script)
        self.assertIn("-x64-unsigned.dmg", manifest_script)
        self.assertIn("-arm64-unsigned.dmg", manifest_script)
        notes = UPDATE_NOTES.read_text(encoding="utf-8")
        self.assertLessEqual(len(notes), 5000)
        self.assertIn("1.0.4", notes)

    def test_workflow_builds_explicitly_unsigned_macos_dmgs(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("runner: macos-15-intel", workflow)
        self.assertIn("runner: macos-15", workflow)
        self.assertIn("command: dist:mac:x64", workflow)
        self.assertIn("command: dist:mac:arm64", workflow)
        self.assertIn("if: matrix.ffmpeg_target != 'none'", workflow)
        self.assertIn('CSC_IDENTITY_AUTO_DISCOVERY: "false"', workflow)
        publish = workflow.split("  publish-release:", 1)[1]
        self.assertIn('"*.dmg" "Streamiov.Studio-${APP_VERSION}-x64-unsigned.dmg"', publish)
        self.assertIn('"*.dmg" "Streamiov.Studio-${APP_VERSION}-arm64-unsigned.dmg"', publish)

    def test_workflow_skips_publishing_when_the_release_already_exists(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")
        publish = workflow.split("  publish-release:", 1)[1]
        self.assertIn('echo "skip=true" >> "$GITHUB_OUTPUT"', publish)
        self.assertIn('echo "skip=false" >> "$GITHUB_OUTPUT"', publish)
        self.assertIn("Release studio-v$APP_VERSION already exists; skipping publication for this commit.", publish)
        self.assertIn("updating only the newly built assets because this was explicitly requested", publish)
        self.assertIn("UPDATE_EXISTING: ${{ inputs.update_existing_release }}", publish)
        self.assertNotIn("Bump the app version before publishing new installers.", publish)
        self.assertGreaterEqual(publish.count("if: steps.version.outputs.skip != 'true'"), 5)

    def test_public_pages_link_the_published_release_assets(self):
        base = "https://github.com/schaffrathsascha318-ship-it/streamiov---core/releases/download/studio-v1.0.4/"
        download = DOWNLOAD_PAGE.read_text(encoding="utf-8")
        promo = PROMO_PAGE.read_text(encoding="utf-8")
        for asset in (
            "Streamiov.Studio.Setup.1.0.4-x64.exe",
            "Streamiov.Studio.Setup.1.0.4-arm64.exe",
            "Streamiov.Studio-1.0.4-x64.AppImage",
            "Streamiov.Studio-1.0.4-arm64.AppImage",
            "streamiov-studio_1.0.4_amd64.deb",
            "streamiov-studio_1.0.4_arm64.deb",
            "SHA256SUMS.txt",
        ):
            with self.subTest(asset=asset):
                self.assertIn(base + asset, download)
        for page in (DOWNLOAD_PAGE, PROMO_PAGE):
            with self.subTest(page=page.name):
                markup = page.read_text(encoding="utf-8")
                self.assertIn(base, markup)
                self.assertNotIn("Release ausstehend", markup)
                self.assertNotIn("Release vorbereitet", markup)
                self.assertNotIn("Veröffentlichung steht aus", markup)
        self.assertIn("Kein macOS-Artefakt in 1.0.4", download)
        self.assertNotIn("release/download/studio-v1.0.4/Streamiov.Studio-1.0.4-x64-unsigned.dmg", download)


if __name__ == "__main__":
    unittest.main()
