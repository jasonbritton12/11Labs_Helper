"""Persist caption export batch facts on backward-compatible Job records."""

from __future__ import annotations

from pathlib import Path

from .captions import (
    CaptionEditorialCoverage,
    CaptionIssueSeverity,
    CaptionRenderingDisposition,
    CaptionTechnicalStatus,
    CaptionExceptionState,
    ExportResult,
)
from .config import Deliverable
from .jobs.models import Job

CAPTION_ARTIFACT_KEYS = frozenset({"srt", "vtt", "caption_document", "caption_qc"})


def requests_captions(deliverables) -> bool:
    return any(item in (Deliverable.SRT, Deliverable.VTT) for item in deliverables)


def apply_export_result(
    job: Job,
    exported: ExportResult,
    deliverables,
    *,
    incomplete: bool = False,
) -> None:
    """Apply actual written paths and replace the current caption-batch record."""

    requested = tuple(deliverables)
    caption_attempt = requests_captions(requested)
    old_caption_paths = {
        key: value
        for key, value in job.artifacts.items()
        if key in CAPTION_ARTIFACT_KEYS
    }
    if caption_attempt:
        for key in CAPTION_ARTIFACT_KEYS:
            job.artifacts.pop(key, None)
    for key, value in exported.paths.items():
        job.artifacts[key] = value

    if not caption_attempt or exported.interpretation is None or exported.report is None:
        return

    report = exported.report
    job.latest_caption_options = exported.options.model_copy(deep=True)
    job.caption_qc_summary = {
        "technical_status": report.technical_status.value,
        "editorial_coverage": report.editorial_coverage.value,
        "exception_state": report.exception_state.value,
        "severity_counts": dict(report.severity_counts),
        "disposition": exported.disposition.value,
        "document_hash": exported.interpretation.document.document_hash,
        "report_hash": report.report_hash,
    }
    retained = {
        key: value
        for key, value in old_caption_paths.items()
        if key not in exported.paths and Path(value).exists()
    }
    job.latest_caption_batch = {
        "document_hash": exported.interpretation.document.document_hash,
        "report_hash": report.report_hash,
        "disposition": exported.disposition.value,
        "requested_formats": [
            item.value
            for item in requested
            if item in (Deliverable.SRT, Deliverable.VTT)
        ],
        "written_formats": [
            key for key in ("srt", "vtt") if key in exported.paths
        ],
        "paths": {
            key: value
            for key, value in exported.paths.items()
            if key in CAPTION_ARTIFACT_KEYS
        },
        "retained_paths": retained,
        "incomplete": incomplete,
    }


def completion_message(exported: ExportResult, *, empty: bool = False) -> str:
    if empty:
        return "No speech detected"
    report = exported.report
    if report is None:
        return "Completed"
    if exported.disposition is CaptionRenderingDisposition.BLOCKED:
        return "Caption export blocked"
    if report.exception_state is CaptionExceptionState.APPROVED:
        return "Completed — caption exception approved"
    if report.editorial_coverage is CaptionEditorialCoverage.APPROVAL_REQUIRED:
        return "Caption review required"
    if report.technical_status is CaptionTechnicalStatus.FAILED:
        return "Completed — caption QC failed"
    if any(item.severity is CaptionIssueSeverity.WARNING for item in report.findings):
        return "Completed — caption warnings"
    return "Completed"
