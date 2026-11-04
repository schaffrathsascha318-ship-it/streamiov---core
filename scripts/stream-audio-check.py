#!/usr/bin/env python3
"""Verify the complete audio path without buying anything.

Starts a local RTMP listener, lets STREAMIOV Studio send to it, and then checks
the recorded file with ffprobe. This proves what the encoder actually sent:
microphone, system audio, mixer gains and the Schutzregie mute all have to be
audible in the recording, not just on the local level meter.

Examples:
    python3 scripts/stream-audio-check.py
    # then use rtmp://127.0.0.1:1935/live/test in Studio

    python3 scripts/stream-audio-check.py --analyze /tmp/stream-test.flv
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

DEFAULT_TIMEOUT = 600
DEFAULT_MIN_DURATION = 5.0


def fail(message: str, code: int = 1) -> None:
    print(json.dumps({"ok": False, "error": message}, indent=2, ensure_ascii=False))
    raise SystemExit(code)


def analyze(path: Path, args: argparse.Namespace) -> dict[str, object]:
    if not path.is_file():
        fail(f"Datei fehlt: {path}")
    if not shutil.which("ffprobe"):
        fail("ffprobe fehlt. Installiere FFmpeg mit ffprobe (kostenlos).", 2)

    probe = subprocess.run(
        ["ffprobe", "-hide_banner", "-loglevel", "error", "-print_format", "json",
         "-show_streams", "-show_format", str(path)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if probe.returncode != 0:
        fail(f"ffprobe konnte die Datei nicht lesen: {probe.stderr.strip()[:400]}")
    data = json.loads(probe.stdout or "{}")
    streams = data.get("streams", [])
    video = next((item for item in streams if item.get("codec_type") == "video"), None)
    audio = next((item for item in streams if item.get("codec_type") == "audio"), None)

    duration = 0.0
    try:
        duration = float(data.get("format", {}).get("duration") or 0.0)
    except (TypeError, ValueError):
        duration = 0.0

    checks: list[dict[str, object]] = []

    def check(name: str, ok: bool, detail: object = None) -> None:
        checks.append({"check": name, "ok": bool(ok), **({"detail": detail} if detail is not None else {})})

    check("video stream present", video is not None)
    check("audio stream present", audio is not None)
    if video:
        check(f"video codec is {args.expect_video}", video.get("codec_name") == args.expect_video,
              video.get("codec_name"))
    if audio:
        check(f"audio codec is {args.expect_audio}", audio.get("codec_name") == args.expect_audio,
              audio.get("codec_name"))
        check(f"sample rate is {args.expect_rate} Hz", int(audio.get("sample_rate") or 0) == args.expect_rate,
              audio.get("sample_rate"))
        check(f"channels are {args.expect_channels}", int(audio.get("channels") or 0) == args.expect_channels,
              audio.get("channels"))
    check(f"duration >= {args.min_duration:g}s", duration >= args.min_duration, round(duration, 2))

    audio_duration = float(audio.get("duration") or duration or 0.0) if audio else 0.0
    video_duration = float(video.get("duration") or duration or 0.0) if video else 0.0
    drift = abs(audio_duration - video_duration)
    check(f"audio/video drift <= {args.max_drift:g}s", bool(audio and video) and drift <= args.max_drift,
          round(drift, 3))

    ok = all(item["ok"] for item in checks)
    return {
        "ok": ok,
        "file": str(path),
        "duration_seconds": round(duration, 2),
        "video": {key: video.get(key) for key in ("codec_name", "width", "height")} if video else None,
        "audio": {key: audio.get(key) for key in ("codec_name", "sample_rate", "channels")} if audio else None,
        "checks": checks,
        "note": "Metadaten belegen Codec, Rate, Kanäle und Dauer. Hörbarkeit und Lippen-/Ton-Sync zusätzlich manuell prüfen.",
    }


def record(args: argparse.Namespace) -> Path:
    if not shutil.which("ffmpeg"):
        fail("ffmpeg fehlt. Installiere FFmpeg mit libx264, AAC und RTMP (kostenlos).", 2)
    if not shutil.which("ffprobe"):
        fail("ffprobe fehlt. Installiere FFmpeg mit ffprobe (kostenlos).", 2)

    out = Path(args.out).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    handle, log_name = tempfile.mkstemp(prefix="streamiov-rtmp-", suffix=".log")
    os.close(handle)
    error_log = Path(log_name)
    command = [
        "ffmpeg", "-hide_banner", "-loglevel", "warning", "-y",
        "-listen", "1", "-i", args.url, "-c", "copy", str(out),
    ]
    print(json.dumps({
        "action": "listen",
        "url": args.url,
        "output": str(out),
        "next": "In Studio dieses RTMP-Ziel eintragen, Kamera/Mikrofon aktivieren und senden.",
        "timeout_seconds": args.timeout,
    }, indent=2, ensure_ascii=False), flush=True)

    with error_log.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=log)
        deadline = time.monotonic() + args.timeout
        try:
            while process.poll() is None:
                if time.monotonic() >= deadline:
                    process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                    fail(f"Kein Stream innerhalb von {args.timeout}s empfangen.")
                time.sleep(1)
        except KeyboardInterrupt:
            process.terminate()
            process.wait(timeout=10)
            raise

    if process.returncode != 0:
        detail = error_log.read_text(encoding="utf-8", errors="replace").strip()[-600:]
        fail(f"RTMP-Empfang fehlgeschlagen (Exit {process.returncode}): {detail}")
    if not out.is_file() or out.stat().st_size == 0:
        fail("Der Empfänger hat keine Daten geschrieben.")
    error_log.unlink(missing_ok=True)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", default="rtmp://127.0.0.1:1935/live/test",
                        help="RTMP-Ziel, das Studio senden soll (Standard: %(default)s)")
    parser.add_argument("--out", default="streamiov-audio-check.flv",
                        help="Aufnahmedatei des lokalen Empfängers (Standard: %(default)s)")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT,
                        help="Sekunden, die auf den Stream gewartet wird (Standard: %(default)s)")
    parser.add_argument("--analyze", metavar="FILE",
                        help="Nur eine vorhandene Aufnahme prüfen, nichts empfangen")
    parser.add_argument("--min-duration", type=float, default=DEFAULT_MIN_DURATION)
    parser.add_argument("--max-drift", type=float, default=0.5)
    parser.add_argument("--expect-video", default="h264")
    parser.add_argument("--expect-audio", default="aac")
    parser.add_argument("--expect-rate", type=int, default=48000)
    parser.add_argument("--expect-channels", type=int, default=2)
    args = parser.parse_args()

    path = Path(args.analyze).expanduser() if args.analyze else record(args)
    result = analyze(path, args)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    raise SystemExit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
