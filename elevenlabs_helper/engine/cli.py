"""Headless CLI — the same engine used by the GUI, runnable in SDVI Rally / containers.

V1 uploads a ready audio file (e.g. .mp3) directly; no conversion.

Examples:
    elevenlabs-helper transcribe clip.mp3 --out ./out --formats srt,vtt,docx
    elevenlabs-helper isolate interview.mp4 --out ./out
    elevenlabs-helper inspect clip.mp3
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .auth import MissingApiKeyError, get_api_key
from .captions import CaptionExportOptions, CaptionExportPolicy, CaptionTimingMode, load_caption_overlay_file
from .config import (
    DEFAULT_DELIVERABLES,
    Deliverable,
    EngineSettings,
    resolve_caption_options,
)
from .exporters.writer import export_deliverables
from .jobs.models import Job, JobStatus, JobType
from .media.inspect import (
    human_duration,
    human_size,
    inspect,
    limit_warnings,
    voice_isolation_limit_warnings,
)
from .processors.base import ProcessContext
from .processors.speech_to_text import SpeechToTextProcessor
from .processors.voice_isolation import VoiceIsolationProcessor
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
    if getattr(args, "caption_timing", None):
        settings.caption_timing_mode = CaptionTimingMode(args.caption_timing)
    if getattr(args, "caption_profile", None):
        settings.caption_profile_id = args.caption_profile
    return settings


def _caption_options_from_args(
    settings: EngineSettings,
    args: argparse.Namespace,
    *,
    seed: CaptionExportOptions | None = None,
    only_if_explicit: bool = False,
) -> CaptionExportOptions | None:
    explicit = any(
        getattr(args, name, None)
        for name in ("caption_timing", "caption_profile", "caption_policy")
    )
    if only_if_explicit and not explicit:
        return None
    base = seed or resolve_caption_options(settings)
    updates = {}
    if getattr(args, "caption_timing", None):
        updates["timing_mode"] = CaptionTimingMode(args.caption_timing)
    if getattr(args, "caption_profile", None):
        updates["profile_id"] = args.caption_profile
        updates["profile_version"] = "1"
    if getattr(args, "caption_policy", None):
        updates["export_policy"] = CaptionExportPolicy(args.caption_policy)
    return base.model_copy(update=updates, deep=True)


def _caption_cli_status(summary: dict | None) -> int:
    if not summary:
        return 0
    counts = summary.get("severity_counts") or {}
    warning_count = int(counts.get("warning", 0))
    failure_count = int(counts.get("failure", 0))
    blocker_count = int(counts.get("blocker", 0))
    approved_exception = (
        summary.get("exception_state") == "approved"
        and summary.get("disposition") == "written"
        and blocker_count == 0
    )
    if warning_count or failure_count or blocker_count:
        print(
            "  caption QC: "
            f"{summary.get('technical_status', 'unknown')} "
            f"({warning_count} warning, {failure_count} failure, {blocker_count} blocker)"
            + ("; valid local exception approved" if approved_exception else ""),
            file=sys.stderr,
        )
    if approved_exception and not blocker_count:
        return 0
    if (
        failure_count
        or blocker_count
        or summary.get("editorial_coverage") == "approval_required"
        or summary.get("disposition") == "blocked"
    ):
        return 3
    return 0


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
        job.staged_caption_options = _caption_options_from_args(
            settings,
            args,
            seed=job.staged_caption_options,
        )
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
        qc_exit = _caption_cli_status(job.caption_qc_summary)
        if exit_code == 0 and qc_exit:
            exit_code = qc_exit
    return exit_code


def cmd_isolate(args: argparse.Namespace) -> int:
    """Run the Voice Isolation workflow explicitly for one or more files."""
    try:
        api_key = get_api_key()
    except MissingApiKeyError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    settings = EngineSettings.load()
    if args.out:
        settings.output_root = Path(args.out)
    processor = VoiceIsolationProcessor()
    ctx = ProcessContext(
        api_key=api_key, settings=settings, base_url=args.base_url, on_progress=_progress
    )

    exit_code = 0
    for source in args.inputs:
        job = make_job(source, settings, job_type=JobType.VOICE_ISOLATION)
        try:
            warnings = voice_isolation_limit_warnings(inspect(source))
        except Exception:
            warnings = []
        if warnings and not args.force:
            for warning in warnings:
                print(f"  WARNING: {warning}", file=sys.stderr)
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


def cmd_history(args: argparse.Namespace) -> int:
    from .service import Engine

    engine = Engine()
    for job in engine.jobs():
        has_hist = bool(job.history_json and Path(job.history_json).exists())
        print(f"{job.id}  {job.status.value:10s}  history={'yes' if has_hist else 'no '}  {job.source_name}")
    return 0


def cmd_reexport(args: argparse.Namespace) -> int:
    from .config import Deliverable
    from .history import load_history_file
    from .service import Engine

    formats = None
    if args.formats:
        formats = [Deliverable(f.strip()) for f in args.formats.split(",") if f.strip()]

    target = args.target
    summary = None
    try:
        if Path(target).exists():
            # Path mode: re-export directly from a JSON file (history or a saved copy).
            settings = EngineSettings.load()
            result = load_history_file(target)
            out_dir = Path(args.out) if args.out else Path(target).parent
            stem = Path(target).name.split(".")[0]
            exported = export_deliverables(
                result,
                out_dir,
                stem,
                formats or list(DEFAULT_DELIVERABLES),
                caption_options=_caption_options_from_args(settings, args),
                overlay=(load_caption_overlay_file(args.caption_overlay) if args.caption_overlay else None),
            )
            arts = {kind: Path(path) for kind, path in exported.paths.items()}
            if exported.report is not None:
                summary = {
                    "technical_status": exported.report.technical_status.value,
                    "editorial_coverage": exported.report.editorial_coverage.value,
                    "severity_counts": dict(exported.report.severity_counts),
                    "disposition": exported.disposition.value,
                }
        else:
            if args.caption_overlay:
                raise ValueError("--caption-overlay is only valid with an explicit transcript JSON path; job-ID re-export loads that job's named overlay")
            # Job-id mode: preserve the latest batch unless a flag overrides it.
            engine = Engine()
            try:
                job = engine.store.get(target)
                seed = None
                if job is not None:
                    seed = job.latest_caption_options or job.staged_caption_options
                options = _caption_options_from_args(
                    engine.settings,
                    args,
                    seed=seed,
                    only_if_explicit=True,
                )
                arts = engine.reexport(
                    target,
                    deliverables=formats,
                    out_dir=args.out,
                    caption_options=options,
                )
                saved = engine.store.get(target)
                summary = saved.caption_qc_summary if saved is not None else None
            finally:
                engine.stop()
    except Exception as exc:  # noqa: BLE001 - CLI turns export/runtime failures into exit 1.
        print(f"error: {exc}", file=sys.stderr)
        return 1
    for kind, path in sorted(arts.items()):
        print(f"  {kind}: {path}")
    return _caption_cli_status(summary)


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
    _add_caption_args(t)
    t.set_defaults(func=cmd_transcribe)

    i = sub.add_parser(
        "isolate",
        help="Extract dialog from WAV, MP3, or MP4 with ElevenLabs Voice Isolation",
    )
    i.add_argument("inputs", nargs="+", help="Source WAV, MP3, or MP4 files")
    i.add_argument("--out", help="Output root dir (default: alongside each source)")
    i.add_argument(
        "--force",
        action="store_true",
        help="Proceed even if over Voice Isolation size/duration limits",
    )
    i.add_argument("--base-url", default="https://api.elevenlabs.io")
    i.set_defaults(func=cmd_isolate)

    e = sub.add_parser("inspect", help="Show file size/duration and any limit warnings")
    e.add_argument("inputs", nargs="+")
    e.set_defaults(func=cmd_inspect)

    h = sub.add_parser("history", help="List past jobs and whether re-export is available")
    h.set_defaults(func=cmd_history)

    r = sub.add_parser("reexport", help="Regenerate deliverables from saved JSON (no API cost)")
    r.add_argument("target", help="A job id (from `history`) or a path to a transcript .json")
    r.add_argument("--out", help="Output dir override (default: saved job dir / alongside JSON)")
    r.add_argument("--formats", help="Comma list: srt,vtt,docx,json (default: job's / SRT+VTT)")
    r.add_argument(
        "--caption-overlay",
        help="Explicit caption overlay JSON for JSON-path re-export; no overlay filename is inferred",
    )
    _add_caption_args(r)
    r.set_defaults(func=cmd_reexport)
    return parser


def _add_caption_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--caption-timing",
        choices=[item.value for item in CaptionTimingMode],
        help="Caption timing: house authors timing; source keeps ElevenLabs cue timing",
    )
    parser.add_argument(
        "--caption-profile",
        choices=["house-english-v1"],
        help="Named caption authoring profile",
    )
    parser.add_argument(
        "--caption-policy",
        choices=[item.value for item in CaptionExportPolicy],
        help="draft writes faithful failed QC captions; strict blocks their replacement",
    )


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
