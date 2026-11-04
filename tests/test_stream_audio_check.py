import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "stream-audio-check.py"


class StreamAudioCheckTests(unittest.TestCase):
    def run_script(self, *args, env=None):
        return subprocess.run(
            [sys.executable, str(SCRIPT), *[str(arg) for arg in args]],
            capture_output=True,
            text=True,
            timeout=180,
            env=env,
        )

    def test_help_documents_the_local_loopback(self):
        result = self.run_script("--help")
        self.assertEqual(result.returncode, 0)
        self.assertIn("rtmp://127.0.0.1", result.stdout)
        self.assertIn("ffprobe", result.stdout)

    def test_missing_ffmpeg_is_reported_without_a_traceback(self):
        env = dict(os.environ)
        env["PATH"] = ""
        result = self.run_script("--out", Path(tempfile.gettempdir()) / "unused.flv", env=env)
        self.assertEqual(result.returncode, 2)
        self.assertIn("ffmpeg", result.stdout)
        self.assertNotIn("Traceback", result.stderr)

    def test_missing_file_is_rejected(self):
        result = self.run_script("--analyze", ROOT / "does-not-exist.flv")
        self.assertEqual(result.returncode, 1)
        self.assertIn("Datei fehlt", result.stdout)

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg/ffprobe not installed")
    def test_analysis_accepts_a_complete_aac_h264_recording(self):
        with tempfile.TemporaryDirectory() as tmp:
            recording = Path(tmp) / "sample.flv"
            build = subprocess.run(
                [
                    "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                    "-f", "lavfi", "-i", "testsrc=size=320x240:rate=30",
                    "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
                    "-t", "1", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-ac", "2", "-ar", "48000", str(recording),
                ],
                capture_output=True,
                text=True,
                timeout=120,
            )
            self.assertEqual(build.returncode, 0, build.stderr)
            result = self.run_script("--analyze", recording, "--min-duration", "0.5")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            report = json.loads(result.stdout)
            self.assertTrue(report["ok"])
            self.assertEqual(report["audio"]["codec_name"], "aac")
            self.assertEqual(report["audio"]["channels"], 2)


if __name__ == "__main__":
    unittest.main()
