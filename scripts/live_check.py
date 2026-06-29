#!/usr/bin/env python3
"""Live end-to-end check against the REAL ElevenLabs Scribe API.

This is the one thing the mock tests can't cover: it confirms the request
parameters are accepted and the response shape matches our models, on a real
account. It spends real credits — use a short clip.

The key is read from the macOS Keychain (if you've saved one in the app) or the
ELEVENLABS_API_KEY environment variable. It is NEVER printed.

Usage:
    python scripts/live_check.py path/to/clip_with_speech.mp3 [--out DIR]
    ELEVENLABS_API_KEY=sk-... python scripts/live_check.py clip.mp3

Exit codes: 0 = success, 1 = transcription/validation failed, 2 = no key / bad input.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow running from a checkout without installing.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from elevenlabs_helper.engine.auth import MissingApiKeyError, get_api_key  # noqa: E402
from elevenlabs_helper.engine.config import EngineSettings  # noqa: E402
from elevenlabs_helper.engine.elevenlabs.client import friendly_error  # noqa: E402
from elevenlabs_helper.engine.jobs.models import Job  # noqa: E402
from elevenlabs_helper.engine.media.inspect import human_duration, human_size, inspect  # noqa: E402
from elevenlabs_helper.engine.processors.base import ProcessContext  # noqa: E402
from elevenlabs_helper.engine.processors.speech_to_text import SpeechToTextProcessor  # noqa: E402
from elevenlabs_helper.engine.service import make_job  # noqa: E402


def _progress(job: Job) -> None:
    print(f"  [{int(job.progress * 100):3d}%] {job.status.value}: {job.message}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Live ElevenLabs Scribe check")
    parser.add_argument("input", help="A short .mp3 WITH speech")
    parser.add_argument("--out", help="Output dir (default: alongside the source)")
    parser.add_argument("--base-url", default="https://api.elevenlabs.io")
    args = parser.parse_args(argv)

    source = Path(args.input)
    if not source.exists():
        print(f"error: file not found: {source}", file=sys.stderr)
        return 2

    try:
        api_key = get_api_key()
    except MissingApiKeyError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    info = inspect(source)
    dur = human_duration(info.duration_secs) if info.duration_secs else "unknown"
    print(f"==> {source.name}  ({human_size(info.size_bytes)}, {dur})", file=sys.stderr)
    print("    Sending to ElevenLabs Scribe (real API, real credits)…", file=sys.stderr)

    settings = EngineSettings()
    if args.out:
        settings.output_root = Path(args.out)
    job = make_job(source, settings)
    job.acknowledged_oversize = True  # this is a manual check; proceed regardless
    ctx = ProcessContext(
        api_key=api_key, settings=settings, base_url=args.base_url, on_progress=_progress
    )

    try:
        SpeechToTextProcessor().run(job, ctx)
    except Exception as exc:  # noqa: BLE001
        print(f"\nFAILED: {friendly_error(str(exc))}\n  raw: {exc}", file=sys.stderr)
        return 1

    # Validate response shape against our model by re-reading the canonical JSON.
    print("\n--- RESULT ----------------------------------------------------")
    raw_path = job.artifacts.get("json")
    if raw_path and Path(raw_path).exists():
        import json

        data = json.loads(Path(raw_path).read_text())
        words = data.get("words", [])
        speakers = {w.get("speaker_id") for w in words if w.get("speaker_id")}
        print(f"language      : {data.get('language_code')}")
        print(f"duration_secs : {data.get('audio_duration_secs')}")
        print(f"word count    : {len(words)}")
        print(f"speakers seen : {len(speakers)} ({', '.join(sorted(s for s in speakers if s)) or 'none'})")
        print(f"text (first 200 chars):\n  {data.get('text', '')[:200]}")
    print("\ndeliverables:")
    for kind, path in sorted(job.artifacts.items()):
        print(f"  {kind:5s}: {path}")

    if job.message == "No speech detected":
        print("\nNOTE: API returned an empty transcript — try a clip with clear speech.", file=sys.stderr)
    print("\nLive check OK — Scribe params accepted and response parsed.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
