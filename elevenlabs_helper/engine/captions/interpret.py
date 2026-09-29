"""Pure assembly of source analysis, composition, timing, and caption QC."""

from __future__ import annotations

from typing import Any, Iterable

from .compose import CompositionIssue, compose_caption_plan
from .models import (
    CaptionContext, CaptionDocument, CaptionEditorialCoverage, CaptionEvent, CaptionExportOptions,
    CaptionInterpretation, CaptionIssueSeverity, CaptionProfile, CaptionQCIssue,
    CaptionQCReport, CaptionSource, CaptionTechnicalStatus, CaptionTimingMode,
)
from .profiles import get_caption_profile
from .qc import apply_caption_approvals, source_findings_to_issues, validate_document
from .source import CaptionSourceAnalysis
from .timing import TimingFinding, resolve_caption_timing
from .overlays import (
    CaptionApprovalLedger,
    CaptionOverlay,
    InvalidCaptionApprovals,
    InvalidCaptionOverlay,
    apply_caption_overlay,
)


def _issue(rule_id: str, severity: CaptionIssueSeverity, message: str, indices: Iterable[int] = (), actual: object = None, threshold: object = None) -> CaptionQCIssue:
    return CaptionQCIssue(rule_id=rule_id, severity=severity, source_token_indices=tuple(indices), actual_value=actual, threshold=threshold, message=message)


def _profile(options: CaptionExportOptions) -> CaptionProfile:
    return get_caption_profile(options.profile_id, options.profile_version)


def _control_findings(source: CaptionSource) -> tuple[CaptionQCIssue, ...]:
    findings: list[CaptionQCIssue] = []
    for token in source.tokens:
        if "\r" in token.text or "\n" in token.text:
            findings.append(_issue("SOURCE_EMBEDDED_LINE_CONTROL", CaptionIssueSeverity.BLOCKER, "Source text contains an embedded line control and cannot become a renderable caption event.", (token.source_word_index,)))
        if token.invalid_numeric_values or token.original_start is None or token.original_end is None:
            findings.append(_issue("SOURCE_TOKEN_UNTIMED", CaptionIssueSeverity.BLOCKER, "Meaningful source content lacks usable timestamps.", (token.source_word_index,)))
        elif token.original_start < 0 or token.original_end <= token.original_start:
            findings.append(_issue("SOURCE_SPEECH_TIME_INVALID", CaptionIssueSeverity.BLOCKER, "Meaningful source content has negative, reversed, or zero duration.", (token.source_word_index,), {"start": token.original_start, "end": token.original_end}))
    for cue in source.baseline_cues:
        if "\r" in cue.text or "\n" in cue.text:
            findings.append(_issue("SOURCE_EMBEDDED_LINE_CONTROL", CaptionIssueSeverity.BLOCKER, "Baseline cue text contains an embedded line control and cannot become a renderable caption event.", cue.source_word_indices))
    return tuple(findings)


def _composition_issues(issues: Iterable[CompositionIssue]) -> tuple[CaptionQCIssue, ...]:
    output: list[CaptionQCIssue] = []
    for finding in issues:
        if finding.rule_id in {"SOURCE_TRACE_UNAVAILABLE", "SOURCE_REFERENCE_MISSING", "SOURCE_TEXT_MISMATCH", "SOURCE_CONTENT_LEDGER_INCOMPLETE"}:
            severity = CaptionIssueSeverity.BLOCKER
        elif finding.rule_id in {"LINE_CAPACITY_EXCEEDED", "SINGLE_WORD_OVERLONG"}:
            severity = CaptionIssueSeverity.FAILURE
        else:
            severity = CaptionIssueSeverity.WARNING
        output.append(_issue(finding.rule_id, severity, finding.message, finding.source_token_indices))
    return tuple(output)


def _timing_issues(findings: Iterable[TimingFinding]) -> tuple[CaptionQCIssue, ...]:
    return tuple(
        _issue(
            finding.rule_id,
            CaptionIssueSeverity.BLOCKER if finding.rule_id in {"SOURCE_CUE_UNAVAILABLE", "SOURCE_CUE_UNTIMED", "SOURCE_CUE_TIME_INVALID", "SOURCE_TOKEN_UNTIMED", "SOURCE_SPEECH_TIME_INVALID", "PROGRAM_DURATION_INVALID"} else CaptionIssueSeverity.FAILURE,
            finding.message,
            finding.source_token_indices,
            finding.actual_value,
            finding.threshold,
        )
        for finding in findings
    )


def _report_with_extra(document: CaptionDocument, base: CaptionQCReport, extra: Iterable[CaptionQCIssue]) -> CaptionQCReport:
    findings = tuple(extra) + base.findings
    blocker = any(item.severity is CaptionIssueSeverity.BLOCKER for item in findings)
    failure = any(item.severity is CaptionIssueSeverity.FAILURE for item in findings)
    warning = any(item.severity is CaptionIssueSeverity.WARNING for item in findings)
    status = CaptionTechnicalStatus.BLOCKED if blocker else (CaptionTechnicalStatus.FAILED if failure else (CaptionTechnicalStatus.WARNING if warning else CaptionTechnicalStatus.PASS))
    editorial = (
        CaptionEditorialCoverage.APPROVAL_REQUIRED
        if any(
            item.rule_id.endswith("_REVIEW_REQUIRED")
            or item.rule_id == "CAPTION_OVERLAY_INVALID"
            for item in findings
        )
        else base.editorial_coverage
    )
    return base.model_copy(update={"findings": findings, "technical_status": status, "editorial_coverage": editorial, "document_hash": document.document_hash})


def interpret_captions(
    source: CaptionSource | CaptionSourceAnalysis,
    options: CaptionExportOptions,
    context: CaptionContext | None = None,
    overlay: Any = None,
    approvals: Any = None,
) -> CaptionInterpretation:
    """Create deterministic authored events and a truthful, structured QC report.

    ``overlay`` is always caller-supplied.  P10 deliberately does not discover an
    overlay from an output filename, so JSON-path exports remain explicit.
    """

    analysis = source if isinstance(source, CaptionSourceAnalysis) else None
    caption_source = source.source if analysis is not None else source
    profile = _profile(options)
    preflight = list(_control_findings(caption_source))
    if analysis is not None:
        preflight.extend(source_findings_to_issues(analysis.findings))
        if not analysis.ledger.complete:
            preflight.append(_issue("SOURCE_CONTENT_LEDGER_INCOMPLETE", CaptionIssueSeverity.BLOCKER, "Source content cannot be reconciled completely; synchronized captions were not fabricated.", analysis.ledger.source_word_indices))

    # Do not construct invalid model events merely to diagnose an unrenderable
    # source.  Empty speech remains valid and deliberately follows this path.
    blocked = any(item.severity is CaptionIssueSeverity.BLOCKER for item in preflight)
    if blocked:
        document = CaptionDocument(profile=profile, options=options, source_hash=caption_source.source_hash, speaker_overlay_hash=caption_source.speaker_overlay_hash, context_hash=context.context_hash if context else None, provenance={"timing_mode": options.timing_mode.value, "source_renderable": False})
        base = validate_document(document, source, profile, context)
        return _with_overlay(document, base, caption_source, context, overlay, approvals=approvals)

    plan = compose_caption_plan(
        source,
        timing_mode=options.timing_mode,
        profile=profile,
        context=context,
    )
    timing = resolve_caption_timing(plan.candidates, caption_source, profile, options.timing_mode, context)
    extra = list(_composition_issues(plan.issues))
    extra.extend(_timing_issues(timing.findings))
    events: list[CaptionEvent] = []
    for timed in timing.candidates:
        extra.extend(_composition_issues(timed.candidate.issues))
        extra.extend(_timing_issues(timed.findings))
        if timed.start is None or timed.end is None:
            continue
        try:
            events.append(CaptionEvent(start=timed.start, end=timed.end, authored_lines=timed.candidate.authored_lines, source_token_indices=timed.candidate.source_token_indices, speaker_id=timed.candidate.speaker_id, content_kind=timed.candidate.content_kind, timing_mode=options.timing_mode))
        except ValueError as exc:
            extra.append(_issue("EVENT_UNRENDERABLE", CaptionIssueSeverity.BLOCKER, "A faithful caption event could not be represented for rendering.", timed.candidate.source_token_indices, str(exc)))

    # A partial document would falsely look renderable; preserve diagnostic-only
    # empty output whenever any source candidate failed to make an event.
    if len(events) != len(timing.candidates):
        events = []
    document = CaptionDocument(profile=profile, options=options, source_hash=caption_source.source_hash, speaker_overlay_hash=caption_source.speaker_overlay_hash, context_hash=context.context_hash if context else None, events=tuple(events), provenance={"timing_mode": options.timing_mode.value, "source_renderable": not any(item.severity is CaptionIssueSeverity.BLOCKER for item in extra)})
    base = validate_document(document, source, profile, context)
    initial = _report_with_extra(document, base, extra)
    return _with_overlay(document, initial, caption_source, context, overlay, source_for_qc=source, approvals=approvals)


def _with_overlay(
    document: CaptionDocument,
    report: CaptionQCReport,
    caption_source: CaptionSource,
    context: CaptionContext | None,
    overlay: Any,
    *,
    source_for_qc: CaptionSource | CaptionSourceAnalysis | None = None,
    approvals: Any = None,
) -> CaptionInterpretation:
    """Apply the optional C3 overlay then run the ordinary QC checks again."""

    if overlay is not None and not isinstance(overlay, (CaptionOverlay, InvalidCaptionOverlay)):
        overlay_report = _report_with_extra(
            document,
            report,
            (_issue("CAPTION_OVERLAY_INVALID", CaptionIssueSeverity.BLOCKER, "Caption overlay has an unsupported serialized type and was not applied."),),
        )
        return CaptionInterpretation(document=document, report=_apply_approvals(document, overlay_report, approvals))
    applied = apply_caption_overlay(document, caption_source, context, overlay)
    if not applied.applied:
        return CaptionInterpretation(
            document=document,
            report=_apply_approvals(document, _report_with_extra(document, report, applied.findings), approvals),
        )
    refreshed = validate_document(applied.document, source_for_qc or caption_source, applied.document.profile, context)
    return CaptionInterpretation(
        document=applied.document,
        report=_apply_approvals(applied.document, _report_with_extra(applied.document, refreshed, applied.findings), approvals),
    )


def _apply_approvals(document: CaptionDocument, report: CaptionQCReport, approvals: Any) -> CaptionQCReport:
    if approvals is None:
        return apply_caption_approvals(document, report)
    if isinstance(approvals, InvalidCaptionApprovals):
        return apply_caption_approvals(document, report, approval_record_error=approvals.detail)
    if isinstance(approvals, CaptionApprovalLedger):
        return apply_caption_approvals(document, report, approvals.approvals)
    if isinstance(approvals, (tuple, list)):
        return apply_caption_approvals(document, report, approvals)
    return apply_caption_approvals(document, report, approval_record_error="Caption approvals have an unsupported serialized type and were not used.")
