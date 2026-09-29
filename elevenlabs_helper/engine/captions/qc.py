"""Structured, deterministic technical QC for caption documents."""

from __future__ import annotations

from typing import Iterable

from .glyphs import unsupported_glyphs
from .models import (
    CaptionApproval,
    CaptionContext,
    CaptionContentKind,
    CaptionDocument,
    CaptionEditorialCoverage,
    CaptionExceptionState,
    CaptionIssueSeverity,
    CaptionProfile,
    CaptionQCIssue,
    CaptionQCReport,
    CaptionSource,
    CaptionTechnicalStatus,
)
from .source import CaptionSourceAnalysis, CaptionSourceFinding
from .timing import round_caption_milliseconds


def _issue(
    rule_id: str,
    severity: CaptionIssueSeverity,
    message: str,
    *,
    event_id: str | None = None,
    indices: Iterable[int] = (),
    actual: object = None,
    threshold: object = None,
) -> CaptionQCIssue:
    return CaptionQCIssue(rule_id=rule_id, severity=severity, event_id=event_id, source_token_indices=tuple(indices), actual_value=actual, threshold=threshold, message=message)


_SOURCE_BLOCKERS = frozenset({
    "INVALID_SOURCE_NUMERIC", "UNTIMED_SOURCE_CONTENT", "SOURCE_TRACE_UNAVAILABLE",
    "SOURCE_REFERENCE_DUPLICATED", "SOURCE_REFERENCE_INVALID", "SOURCE_REFERENCE_MISSING",
    "SOURCE_CONTENT_LEDGER_INCOMPLETE", "UNSUPPORTED_SOURCE_TOKEN_TYPE",
})


def _source_issues(
    document: CaptionDocument,
    source: CaptionSource | CaptionSourceAnalysis,
) -> tuple[CaptionQCIssue, ...]:
    """Validate source facts even when callers bypass ``interpret_captions``.

    P05's public ``validate_document`` entry point is deliberately useful to
    renderers and recovery paths.  It therefore cannot assume the document was
    first assembled by the interpreter, which is where malformed source data
    would otherwise be noticed.
    """

    caption_source = _source_for(source)
    findings: list[CaptionQCIssue] = []
    if isinstance(source, CaptionSourceAnalysis):
        findings.extend(source_findings_to_issues(source.findings))
        if not source.ledger.complete:
            findings.append(
                _issue(
                    "SOURCE_CONTENT_LEDGER_INCOMPLETE",
                    CaptionIssueSeverity.BLOCKER,
                    "Source content cannot be reconciled completely; synchronized captions were not fabricated.",
                    indices=source.ledger.source_word_indices,
                )
            )
    for token in caption_source.tokens:
        indices = (token.source_word_index,)
        if "\r" in token.text or "\n" in token.text:
            findings.append(_issue("SOURCE_EMBEDDED_LINE_CONTROL", CaptionIssueSeverity.BLOCKER, "Source text contains an embedded line control and cannot be safely rendered.", indices=indices))
        if token.invalid_numeric_values or token.original_start is None or token.original_end is None:
            findings.append(_issue("SOURCE_TOKEN_UNTIMED", CaptionIssueSeverity.BLOCKER, "Meaningful source content lacks usable timestamps.", indices=indices))
        elif token.original_start < 0 or token.original_end <= token.original_start:
            findings.append(_issue("SOURCE_SPEECH_TIME_INVALID", CaptionIssueSeverity.BLOCKER, "Meaningful source content has negative, reversed, or zero duration.", indices=indices, actual={"start": token.original_start, "end": token.original_end}))
    token_indices = tuple(token.source_word_index for token in caption_source.tokens)
    if len(token_indices) != len(set(token_indices)):
        findings.append(_issue("SOURCE_TOKEN_REFERENCE_DUPLICATED", CaptionIssueSeverity.BLOCKER, "Source token indices are duplicated and cannot form a one-to-one content ledger.", indices=token_indices))
    if token_indices != tuple(sorted(token_indices)):
        findings.append(_issue("SOURCE_TOKEN_INDEX_ORDER_INVALID", CaptionIssueSeverity.BLOCKER, "Source token indices are not in their original response order.", indices=token_indices))
    for cue in caption_source.baseline_cues:
        if "\r" in cue.text or "\n" in cue.text:
            findings.append(_issue("SOURCE_EMBEDDED_LINE_CONTROL", CaptionIssueSeverity.BLOCKER, "Baseline cue text contains an embedded line control and cannot be safely rendered.", indices=cue.source_word_indices))
        if document.options.timing_mode.value == "source":
            if cue.start is None or cue.end is None:
                findings.append(_issue("SOURCE_CUE_UNTIMED", CaptionIssueSeverity.BLOCKER, "A fixed source cue lacks usable timestamps.", indices=cue.source_word_indices))
            elif cue.start < 0 or cue.end <= cue.start:
                findings.append(_issue("SOURCE_CUE_TIME_INVALID", CaptionIssueSeverity.BLOCKER, "A fixed source cue has negative, reversed, or zero duration.", indices=cue.source_word_indices, actual={"start": cue.start, "end": cue.end}))
    if caption_source.tokens:
        cue_indices = tuple(index for cue in caption_source.baseline_cues for index in cue.source_word_indices)
        if cue_indices != token_indices:
            findings.append(_issue("SOURCE_CONTENT_LEDGER_INCOMPLETE", CaptionIssueSeverity.BLOCKER, "Baseline cue references do not consume every source token exactly once in source order.", indices=token_indices, actual={"consumed": cue_indices, "expected": token_indices}))
    if caption_source.tokens and not document.events:
        findings.append(_issue("CAPTION_RENDERING_BLOCKED", CaptionIssueSeverity.BLOCKER, "Meaningful source content has no renderable caption events."))
    return tuple(findings)


def source_findings_to_issues(findings: Iterable[CaptionSourceFinding]) -> tuple[CaptionQCIssue, ...]:
    """Convert source adapter evidence without losing its stable rule identity."""

    return tuple(
        _issue(
            finding.rule_id,
            CaptionIssueSeverity.BLOCKER if finding.rule_id in _SOURCE_BLOCKERS else CaptionIssueSeverity.FAILURE,
            finding.message,
            indices=finding.source_word_indices,
            actual=dict(finding.details),
        )
        for finding in findings
    )


def _source_for(source: CaptionSource | CaptionSourceAnalysis) -> CaptionSource:
    return source.source if isinstance(source, CaptionSourceAnalysis) else source


def _language_verified(language: str | None, profile: CaptionProfile) -> bool:
    if language is None:
        return False
    normalized = language.casefold().replace("_", "-")
    return any(normalized == item or normalized.startswith(f"{item}-") or (item == "en" and normalized == "eng") for item in profile.language_scope)


def validate_document(
    document: CaptionDocument,
    source: CaptionSource | CaptionSourceAnalysis,
    profile: CaptionProfile,
    context: CaptionContext | None = None,
) -> CaptionQCReport:
    """Validate authored events and their rendered-millisecond projection."""

    caption_source = _source_for(source)
    findings: list[CaptionQCIssue] = list(_source_issues(document, source))
    if document.profile.profile_hash != profile.profile_hash:
        findings.append(_issue("PROFILE_MISMATCH", CaptionIssueSeverity.BLOCKER, "The document profile differs from the profile supplied for QC."))

    if not document.events and not caption_source.tokens:
        findings.append(_issue("NO_SPEECH_DETECTED", CaptionIssueSeverity.INFO, "No meaningful timed speech was supplied; the empty caption document is valid."))

    previous = None
    previous_rendered_end: float | None = None
    for event in document.events:
        lines = event.authored_lines
        chars = sum(len(line) for line in lines)
        if len(lines) > profile.max_lines_per_event:
            findings.append(_issue("MAX_LINES_EXCEEDED", CaptionIssueSeverity.FAILURE, "Caption event exceeds the two-line limit.", event_id=event.event_id, indices=event.source_token_indices, actual=len(lines), threshold=profile.max_lines_per_event))
        for line_number, line in enumerate(lines, start=1):
            if "\r" in line or "\n" in line:
                findings.append(_issue("EMBEDDED_LINE_CONTROL", CaptionIssueSeverity.BLOCKER, "Caption text contains an embedded line control and cannot be safely rendered.", event_id=event.event_id, indices=event.source_token_indices, actual=line_number))
            if len(line) > profile.max_chars_per_line:
                findings.append(_issue("LINE_CAPACITY_EXCEEDED", CaptionIssueSeverity.FAILURE, "Caption line exceeds the 32-character limit.", event_id=event.event_id, indices=event.source_token_indices, actual={"line": line_number, "characters": len(line)}, threshold=profile.max_chars_per_line))
        duration = event.end - event.start
        if duration < profile.min_duration_secs:
            findings.append(_issue("DURATION_BELOW_MINIMUM", CaptionIssueSeverity.FAILURE, "Caption duration is below one second.", event_id=event.event_id, indices=event.source_token_indices, actual=duration, threshold=profile.min_duration_secs))
        if duration > profile.max_duration_secs:
            findings.append(_issue("DURATION_ABOVE_MAXIMUM", CaptionIssueSeverity.FAILURE, "Caption duration exceeds seven seconds.", event_id=event.event_id, indices=event.source_token_indices, actual=duration, threshold=profile.max_duration_secs))
        cps = chars / duration
        if cps > profile.cps_warning:
            findings.append(_issue("CPS_ABOVE_MAXIMUM", CaptionIssueSeverity.FAILURE, "Caption reading speed exceeds 20 CPS.", event_id=event.event_id, indices=event.source_token_indices, actual=cps, threshold=profile.cps_warning))
        elif cps > profile.cps_target:
            findings.append(_issue("CPS_ABOVE_TARGET", CaptionIssueSeverity.WARNING, "Caption reading speed exceeds the 17 CPS target.", event_id=event.event_id, indices=event.source_token_indices, actual=cps, threshold=profile.cps_target))
        for glyph in unsupported_glyphs("".join(lines)):
            findings.append(_issue("UNSUPPORTED_GLYPH", CaptionIssueSeverity.FAILURE, "Displayed text contains a glyph absent from the pinned repertoire.", event_id=event.event_id, indices=event.source_token_indices, actual={"position": glyph.position, "character": glyph.character, "code_point": glyph.code_point_label}, threshold=profile.glyph_repertoire_version))
        if event.content_kind is CaptionContentKind.AUDIO_EVENT:
            findings.append(
                _issue(
                    "AUDIO_EVENT_REVIEW_REQUIRED",
                    CaptionIssueSeverity.WARNING,
                    "Audio-event relevance, wording, and music/lyric treatment require editorial review.",
                    event_id=event.event_id,
                    indices=event.source_token_indices,
                )
            )
        if previous is not None and event.start < previous.end:
            findings.append(_issue("EVENT_OVERLAP", CaptionIssueSeverity.FAILURE, "Caption events overlap.", event_id=event.event_id, indices=event.source_token_indices, actual={"previous_end": previous.end, "start": event.start}))
        previous = event

        rendered_start = round_caption_milliseconds(event.start)
        rendered_end = round_caption_milliseconds(event.end)
        rendered_duration = rendered_end - rendered_start
        if rendered_end <= rendered_start:
            findings.append(_issue("RENDERED_ZERO_DURATION", CaptionIssueSeverity.FAILURE, "Millisecond rounding makes the rendered event zero or negative duration.", event_id=event.event_id, indices=event.source_token_indices, actual={"start": rendered_start, "end": rendered_end}))
        else:
            if rendered_duration < profile.min_duration_secs:
                findings.append(_issue("RENDERED_DURATION_BELOW_MINIMUM", CaptionIssueSeverity.FAILURE, "Millisecond rounding makes rendered duration shorter than one second.", event_id=event.event_id, indices=event.source_token_indices, actual=rendered_duration, threshold=profile.min_duration_secs))
            if rendered_duration > profile.max_duration_secs:
                findings.append(_issue("RENDERED_DURATION_ABOVE_MAXIMUM", CaptionIssueSeverity.FAILURE, "Millisecond rounding makes rendered duration longer than seven seconds.", event_id=event.event_id, indices=event.source_token_indices, actual=rendered_duration, threshold=profile.max_duration_secs))
            if chars / rendered_duration > profile.cps_warning:
                findings.append(_issue("RENDERED_CPS_ABOVE_MAXIMUM", CaptionIssueSeverity.FAILURE, "Millisecond rounding makes rendered reading speed exceed 20 CPS.", event_id=event.event_id, indices=event.source_token_indices, actual=chars / rendered_duration, threshold=profile.cps_warning))
            elif chars / rendered_duration > profile.cps_target:
                findings.append(_issue("RENDERED_CPS_ABOVE_TARGET", CaptionIssueSeverity.WARNING, "Millisecond rounding makes rendered reading speed exceed 17 CPS.", event_id=event.event_id, indices=event.source_token_indices, actual=chars / rendered_duration, threshold=profile.cps_target))
        if previous_rendered_end is not None and rendered_start < previous_rendered_end:
            findings.append(_issue("RENDERED_EVENT_OVERLAP", CaptionIssueSeverity.FAILURE, "Millisecond rounding produces overlapping rendered caption events.", event_id=event.event_id, indices=event.source_token_indices, actual={"previous_end": previous_rendered_end, "start": rendered_start}))
        previous_rendered_end = rendered_end

    if not _language_verified(caption_source.language_code, profile):
        findings.append(_issue("LANGUAGE_PROFILE_UNVERIFIED", CaptionIssueSeverity.WARNING, "The English house profile is not verified for the source language.", actual=caption_source.language_code, threshold=profile.language_scope))

    # Frame and shot facts are explicitly coverage, not an inferred timing claim.
    if context is None or context.frame_rate is None:
        findings.append(_issue("FRAME_ACCURACY_NOT_EVALUATED", CaptionIssueSeverity.INFO, "No frame-rate context was supplied; frame accuracy was not evaluated."))
    if context is None or context.shot_change_secs is None:
        findings.append(_issue("SHOT_CONTEXT_NOT_EVALUATED", CaptionIssueSeverity.INFO, "No shot-change context was supplied; shot alignment was not evaluated."))

    dialogue_events = [
        event
        for event in document.events
        if event.content_kind is CaptionContentKind.WORD
    ]
    dialogue_speakers = {
        event.speaker_id for event in dialogue_events if event.speaker_id is not None
    }
    if len(dialogue_speakers) > 1:
        findings.append(
            _issue(
                "SPEAKER_IDENTITY_REVIEW_REQUIRED",
                CaptionIssueSeverity.WARNING,
                "Multiple dialogue speakers are present, but the transcript cannot establish on-screen/off-screen identity; editorial review is required.",
                indices=(
                    index
                    for event in dialogue_events
                    for index in event.source_token_indices
                ),
                actual=sorted(dialogue_speakers),
            )
        )

    has_blocker = any(item.severity is CaptionIssueSeverity.BLOCKER for item in findings)
    has_failure = any(item.severity is CaptionIssueSeverity.FAILURE for item in findings)
    has_warning = any(item.severity is CaptionIssueSeverity.WARNING for item in findings)
    technical = CaptionTechnicalStatus.BLOCKED if has_blocker else (CaptionTechnicalStatus.FAILED if has_failure else (CaptionTechnicalStatus.WARNING if has_warning else CaptionTechnicalStatus.PASS))
    review_required = any(
        item.rule_id.endswith("_REVIEW_REQUIRED") for item in findings
    )
    editorial = (
        CaptionEditorialCoverage.APPROVAL_REQUIRED
        if review_required
        else CaptionEditorialCoverage.NOT_EVALUATED
        if (context is None or context.frame_rate is None or context.shot_change_secs is None)
        else CaptionEditorialCoverage.PARTIAL
    )
    return CaptionQCReport(findings=tuple(findings), technical_status=technical, editorial_coverage=editorial, exception_state=CaptionExceptionState.NONE, options=document.options, document_hash=document.document_hash)


_NON_APPROVABLE_RULE_FRAGMENTS = (
    "SOURCE_",
    "CONTENT_LEDGER",
    "UNRENDERABLE",
    "EMBEDDED_",
    "INVALID",
    "ZERO_DURATION",
    "CAPTION_RENDERING",
    "CAPTION_OVERLAY",
    "PROFILE_MISMATCH",
    "SCHEMA",
    "ALGORITHM",
)


def is_approvable_issue(issue: CaptionQCIssue) -> bool:
    """Whether a finding is a measured exception rather than an integrity defect."""

    return (
        issue.severity in {CaptionIssueSeverity.WARNING, CaptionIssueSeverity.FAILURE}
        and is_actionable_issue(issue)
        and not any(part in issue.rule_id for part in _NON_APPROVABLE_RULE_FRAGMENTS)
    )


def is_actionable_issue(issue: CaptionQCIssue) -> bool:
    """Findings that prevent strict output unless an exact approval exists."""

    return issue.severity is CaptionIssueSeverity.FAILURE or issue.rule_id.endswith("_REVIEW_REQUIRED")


def apply_caption_approvals(
    document: CaptionDocument,
    report: CaptionQCReport,
    approvals: Iterable[CaptionApproval] = (),
    *,
    approval_record_error: str | None = None,
) -> CaptionQCReport:
    """Annotate exact matching findings and derive the report exception state.

    The original measurement/severity remains intact.  Stale records are simply
    unable to match; a corrupt record is an explicit blocker, never a silently
    discarded local exception.
    """

    findings = list(report.findings)
    if approval_record_error:
        findings.append(
            _issue(
                "CAPTION_APPROVAL_RECORD_INVALID",
                CaptionIssueSeverity.BLOCKER,
                approval_record_error,
            )
        )
    approval_records = tuple(approvals)
    approvals_by_finding: dict[int, CaptionApproval] = {}
    for approval in approval_records:
        for issue in report.findings:
            if is_approvable_issue(issue) and approval.matches(document, issue):
                approvals_by_finding[id(issue)] = approval
                break
    # Keep stale decisions visible. Their underlying measurement remains in the
    # report and actionable; this annotation explains why the old local record
    # no longer grants an exception after any bound changed.
    matched_ids = {approval.approval_id for approval in approvals_by_finding.values()}
    invalidated = [approval for approval in approval_records if approval.approval_id not in matched_ids]
    for approval in invalidated:
        findings.append(
            _issue(
                "CAPTION_APPROVAL_INVALIDATED",
                CaptionIssueSeverity.WARNING,
                "A saved caption approval no longer matches the current document or measured finding and was not applied.",
                indices=approval.source_token_indices,
                actual={"approval_id": approval.approval_id, "prior_issue_id": approval.issue_id},
            )
        )
    annotated_items = []
    for issue in report.findings:
        approval = approvals_by_finding.get(id(issue))
        annotated_items.append(
            issue.model_copy(update={"approval_reference": approval.approval_id})
            if approval is not None else issue
        )
    annotated = tuple(annotated_items + findings[len(report.findings):])
    has_blocker = any(item.severity is CaptionIssueSeverity.BLOCKER for item in annotated)
    actionable = [item for item in annotated if is_actionable_issue(item)]
    all_actionable_approved = bool(actionable) and all(
        is_approvable_issue(item) and item.approval_reference is not None
        for item in actionable
    )
    state = (
        CaptionExceptionState.APPROVED
        if not has_blocker and all_actionable_approved
        else CaptionExceptionState.APPROVAL_REQUIRED
        if actionable
        else CaptionExceptionState.NONE
    )
    technical = (
        CaptionTechnicalStatus.BLOCKED
        if has_blocker
        else CaptionTechnicalStatus.FAILED
        if any(item.severity is CaptionIssueSeverity.FAILURE for item in annotated)
        else CaptionTechnicalStatus.WARNING
        if any(item.severity is CaptionIssueSeverity.WARNING for item in annotated)
        else CaptionTechnicalStatus.PASS
    )
    return report.model_copy(
        update={
            "findings": annotated,
            "technical_status": technical,
            "exception_state": state,
            "document_hash": document.document_hash,
        }
    )
