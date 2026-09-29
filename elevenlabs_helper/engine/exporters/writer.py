"""Write selected deliverables from one canonical transcript.

Caption exports are authored once as a :class:`CaptionDocument`; SRT, WebVTT,
and their diagnostic sidecars all describe that same document.  The legacy
``write_deliverables`` API remains available for callers that only need paths.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from ..captions import (
    CaptionContext,
    CaptionEditorialCoverage,
    CaptionExportOptions,
    CaptionExportPolicy,
    CaptionRenderingDisposition,
    CaptionTechnicalStatus,
    CaptionExceptionState,
    CaptionTimingMode,
    ExportResult,
    interpret_captions,
)
from ..captions.source import analyze_caption_source
from ..config import Deliverable
from ..elevenlabs.models import TranscriptionResult
from . import docx as docx_exporter
from . import dub_csv as dub_csv_exporter
from . import srt as srt_exporter
from . import vtt as vtt_exporter
from .canonical import apply_edits, build_transcript

if TYPE_CHECKING:
    from ..edits import SpeakerEdits

_EXT = {
    Deliverable.SRT: "srt",
    Deliverable.VTT: "vtt",
    Deliverable.DOCX: "docx",
    Deliverable.JSON: "json",
    Deliverable.DUB_CSV: "csv",
}
_CAPTION_KEYS = {
    Deliverable.SRT: "srt",
    Deliverable.VTT: "vtt",
}


class ExportWriteError(OSError):
    """An output batch failed after zero or more files were replaced."""

    def __init__(self, message: str, *, written_paths: dict[str, Path]):
        super().__init__(message)
        self.written_paths = dict(written_paths)
        self.export_result: ExportResult | None = None


def deliverable_paths(out_dir, stem: str, deliverables) -> list[Path]:
    """Return every path a requested export may replace.

    Caption document and QC sidecars are implicit parts of any SRT/WebVTT
    request so overwrite prompts can account for them before export.
    """

    out = Path(out_dir)
    selected = tuple(deliverables)
    paths = [out / f"{stem}.{_EXT[item]}" for item in selected if item in _EXT]
    if any(item in _CAPTION_KEYS for item in selected):
        paths.extend(
            (
                out / f"{stem}.caption-document.json",
                out / f"{stem}.caption-qc.json",
            )
        )
    return list(dict.fromkeys(paths))


planned_export_paths = deliverable_paths


def _resolved_options(
    caption_options: CaptionExportOptions | None,
    readable_subtitles: bool | None,
) -> CaptionExportOptions:
    legacy_mode = None
    if readable_subtitles is not None:
        legacy_mode = CaptionTimingMode.HOUSE if readable_subtitles else CaptionTimingMode.SOURCE
    if caption_options is None:
        # Direct legacy callers historically received waveform/source timing.
        return CaptionExportOptions(timing_mode=legacy_mode or CaptionTimingMode.SOURCE)
    if legacy_mode is not None and caption_options.timing_mode is not legacy_mode:
        raise ValueError(
            "caption timing options disagree: caption_options and "
            "readable_subtitles select different modes"
        )
    return caption_options.model_copy(deep=True)


def _disposition(interpretation) -> CaptionRenderingDisposition:
    report = interpretation.report
    if report.technical_status is CaptionTechnicalStatus.BLOCKED:
        return CaptionRenderingDisposition.BLOCKED
    if report.exception_state is CaptionExceptionState.APPROVED:
        # The measurement remains failed/review-required in the sidecar.  A
        # complete set of exact local approvals only authorizes strict output.
        return CaptionRenderingDisposition.WRITTEN
    actionable = (
        report.technical_status is CaptionTechnicalStatus.FAILED
        or report.editorial_coverage is CaptionEditorialCoverage.APPROVAL_REQUIRED
    )
    if actionable:
        if report.options.export_policy is CaptionExportPolicy.STRICT:
            return CaptionRenderingDisposition.BLOCKED
        return CaptionRenderingDisposition.DRAFT
    return CaptionRenderingDisposition.WRITTEN


def _stage_text(path: Path, value: str) -> Path:
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        return temporary
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _stage_file(path: Path, write: Callable[[Path], object]) -> Path:
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    os.close(fd)
    temporary = Path(name)
    try:
        write(temporary)
        with temporary.open("rb") as handle:
            os.fsync(handle.fileno())
        return temporary
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _commit_staged(staged: list[tuple[str, Path, Path]]) -> dict[str, Path]:
    written: dict[str, Path] = {}
    try:
        for key, temporary, target in staged:
            os.replace(temporary, target)
            written[key] = target
        return written
    except Exception as exc:
        for _, temporary, _ in staged:
            temporary.unlink(missing_ok=True)
        raise ExportWriteError(
            f"Export failed after replacing {len(written)} file(s): {exc}",
            written_paths=written,
        ) from exc


def export_deliverables(
    result: TranscriptionResult,
    out_dir: str | Path,
    stem: str,
    deliverables: list[Deliverable],
    *,
    edits: "SpeakerEdits | None" = None,
    caption_options: CaptionExportOptions | None = None,
    context: CaptionContext | None = None,
    overlay=None,
    approvals=None,
    readable_subtitles: bool | None = None,
) -> ExportResult:
    """Render a verified output batch and return its caption/QC facts.

    Every individual destination is staged beside its final path and replaced
    atomically.  A multi-file batch is intentionally not claimed to be atomic;
    ``ExportWriteError.written_paths`` reports any earlier replacements.
    """

    options = _resolved_options(caption_options, readable_subtitles)
    selected = tuple(dict.fromkeys(deliverables))
    caption_requested = any(item in _CAPTION_KEYS for item in selected)
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    transcript = build_transcript(result)
    if edits is not None:
        transcript = apply_edits(transcript, edits)

    interpretation = None
    disposition = CaptionRenderingDisposition.NOT_REQUESTED
    if caption_requested:
        source = analyze_caption_source(result, transcript)
        interpretation = interpret_captions(source, options, context, overlay, approvals)
        disposition = _disposition(interpretation)

    staged: list[tuple[str, Path, Path]] = []
    try:
        # Commit diagnostics first so a later caption-file failure still leaves
        # an inspectable account of the attempted document.
        if interpretation is not None:
            document_path = out_path / f"{stem}.caption-document.json"
            report_path = out_path / f"{stem}.caption-qc.json"
            staged.append(
                (
                    "caption_document",
                    _stage_text(document_path, interpretation.document.model_dump_json(indent=2)),
                    document_path,
                )
            )
            staged.append(
                (
                    "caption_qc",
                    _stage_text(report_path, interpretation.report.model_dump_json(indent=2)),
                    report_path,
                )
            )

        render_captions = disposition in {
            CaptionRenderingDisposition.WRITTEN,
            CaptionRenderingDisposition.DRAFT,
        }
        if render_captions and Deliverable.SRT in selected:
            target = out_path / f"{stem}.srt"
            staged.append(("srt", _stage_text(target, srt_exporter.render_caption_document(interpretation.document)), target))
        if render_captions and Deliverable.VTT in selected:
            target = out_path / f"{stem}.vtt"
            staged.append(("vtt", _stage_text(target, vtt_exporter.render_caption_document(interpretation.document)), target))
        if Deliverable.DOCX in selected:
            target = out_path / f"{stem}.docx"
            staged.append(("docx", _stage_file(target, lambda path: docx_exporter.write(transcript, path)), target))
        if Deliverable.JSON in selected:
            target = out_path / f"{stem}.json"
            staged.append(("json", _stage_text(target, result.model_dump_json(indent=2)), target))
        if Deliverable.DUB_CSV in selected:
            target = out_path / f"{stem}.csv"
            staged.append(("dub_csv", _stage_text(target, dub_csv_exporter.render(transcript)), target))
    except Exception:
        for _, temporary, _ in staged:
            temporary.unlink(missing_ok=True)
        raise

    try:
        written = _commit_staged(staged)
    except ExportWriteError as exc:
        exc.export_result = ExportResult(
            paths={key: str(path) for key, path in exc.written_paths.items()},
            interpretation=interpretation,
            report=interpretation.report if interpretation is not None else None,
            options=options,
            disposition=disposition,
        )
        raise
    return ExportResult(
        paths={key: str(path) for key, path in written.items()},
        interpretation=interpretation,
        report=interpretation.report if interpretation is not None else None,
        options=options,
        disposition=disposition,
    )


def write_deliverables(
    result: TranscriptionResult,
    out_dir: str | Path,
    stem: str,
    deliverables: list[Deliverable],
    *,
    edits: "SpeakerEdits | None" = None,
    readable_subtitles: bool | None = None,
    caption_options: CaptionExportOptions | None = None,
    context: CaptionContext | None = None,
    overlay=None,
    approvals=None,
) -> dict[str, Path]:
    """Compatibility adapter returning every path actually written.

    With neither caption option API supplied, captions keep source timing.  New
    app and CLI paths pass an explicit resolved option snapshot.
    """

    exported = export_deliverables(
        result,
        out_dir,
        stem,
        deliverables,
        edits=edits,
        caption_options=caption_options,
        context=context,
        overlay=overlay,
        approvals=approvals,
        readable_subtitles=readable_subtitles,
    )
    return {key: Path(value) for key, value in exported.paths.items()}
