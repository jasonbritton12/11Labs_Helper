"""Headless CLI — the same engine used by the GUI, runnable in SDVI Rally / containers.

V1 uploads a ready audio file (e.g. .mp3) directly; no conversion.

Examples:
    elevenlabs-helper transcribe clip.mp3 --out ./out --formats srt,vtt,docx
    elevenlabs-helper inspect clip.mp3
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .auth import MissingApiKeyError, get_api_key
from .config import Deliverable, EngineSettings
from .jobs.models import Job, JobStatus
from .media.inspect import human_duration, human_size, inspect, limit_warnings
from .processors.base import ProcessContext
from .processors.speech_to_text import SpeechToTextProcessor
from .service import make_job


def _settings_from_args(args: argparse.Namespace) -> EngineSettings:
    settings = EngineSettings.load()
    if args.out:
        settings.output_root = Path(args.out)
    if getattr(args, "formats", None):
        settings.deliverables = [Deliverable(f.strip()) for f in args.formats.split(",") if f.strip()]
    if getattr(args, "no_diarize", False):
        settings.transcription.diarize = False
    if getattr(args, "language", None):
        settings.transcription.language_code = args.language
    if getattr(args, "tag_events", None) is False:
        settings.transcription.tag_audio_events = False
    return settings


def _progress(job: Job) -> None:
    pct = int(job.progress * 100)
    print(f"  [{pct:3d}%] {job.source_name}: {job.status.value} {job.message}", file=sys.stderr)


def cmd_transcribe(args: argparse.Namespace) -> int:
    try:
        api_key = get_api_key()
    except MissingApiKeyError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    settings = _settings_from_args(args)
    processor = SpeechToTextProcessor()
    ctx = ProcessContext(
        api_key=api_key, settings=settings, base_url=args.base_url, on_progress=_progress
    )

    exit_code = 0
    for source in args.inputs:
        job = make_job(source, settings)
        # Oversize gate: warn, and require --force to proceed past API limits.
        try:
            warnings = limit_warnings(inspect(source))
        except Exception:
            warnings = []
        if warnings and not args.force:
            for w in warnings:
                print(f"  WARNING: {w}", file=sys.stderr)
            print("  Skipping (re-run with --force to try anyway).", file=sys.stderr)
            exit_code = 1
            continue
        job.acknowledged_oversize = bool(warnings)

        print(f"==> {Path(source).name} -> {job.output_dir}", file=sys.stderr)
        try:
            processor.run(job, ctx)
        except Exception as exc:  # noqa: BLE001 - CLI surfaces any failure
            job.status = JobStatus.FAILED
            job.error = str(exc)
            print(f"  FAILED: {exc}", file=sys.stderr)
            exit_code = 1
            continue
        for kind, path in sorted(job.artifacts.items()):
            print(f"  {kind}: {path}")
    return exit_code


def cmd_inspect(args: argparse.Namespace) -> int:
    for source in args.inputs:
        try:
            info = inspect(source)
        except Exception as exc:  # noqa: BLE001
            print(f"{Path(source).name}: error: {exc}", file=sys.stderr)
            continue
        dur = human_duration(info.duration_secs) if info.duration_secs else "unknown duration"
        line = f"{Path(source).name}: {human_size(info.size_bytes)}, {dur}"
        for w in limit_warnings(info):
            line += f"\n  WARNING: {w}"
        print(line)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="elevenlabs-helper", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    t = sub.add_parser("transcribe", help="Transcribe audio files")
    t.add_argument("inputs", nargs="+", help="Source audio files (e.g. .mp3)")
    t.add_argument("--out", help="Output root dir (default: alongside each source)")
    t.add_argument("--formats", help="Comma list: srt,vtt,docx,json (default from settings)")
    t.add_argument("--language", help="Force language code (default: auto-detect)")
    t.add_argument("--no-diarize", action="store_true", help="Disable speaker diarization")
    t.add_argument("--no-tag-events", dest="tag_events", action="store_false", default=None)
    t.add_argument("--force", action="store_true", help="Proceed even if over ElevenLabs limits")
    t.add_argument("--base-url", default="https://api.elevenlabs.io")
    t.set_defaults(func=cmd_transcribe)

    e = sub.add_parser("inspect", help="Show file size/duration and any limit warnings")
    e.add_argument("inputs", nargs="+")
    e.set_defaults(func=cmd_inspect)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
