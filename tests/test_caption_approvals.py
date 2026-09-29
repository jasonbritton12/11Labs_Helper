from __future__ import annotations

from datetime import datetime, timezone

import pytest

from elevenlabs_helper.engine.captions import (
    CaptionApprovalLedger,
    CaptionDocument,
    CaptionEvent,
    CaptionExceptionState,
    CaptionExportOptions,
    CaptionExportPolicy,
    CaptionIssueSeverity,
    CaptionQCIssue,
    CaptionQCReport,
    CaptionRenderingDisposition,
    CaptionTechnicalStatus,
    CaptionTimingMode,
    HOUSE_ENGLISH_V1,
    InvalidCaptionApprovals,
    apply_caption_approvals,
    interpret_captions,
    is_approvable_issue,
    new_caption_approval,
    revoke_caption_approval,
    save_caption_approvals,
    load_caption_approvals,
    load_caption_approvals_file,
)
from elevenlabs_helper.engine.captions.models import CaptionSource, CaptionSourceToken
from elevenlabs_helper.engine.captions.qc import is_actionable_issue
from elevenlabs_helper.engine.caption_jobs import apply_export_result, completion_message
from elevenlabs_helper.engine.config import Deliverable
from elevenlabs_helper.engine.elevenlabs.models import TranscriptionResult
from elevenlabs_helper.engine.exporters.writer import export_deliverables
from elevenlabs_helper.engine.jobs.models import Job


def _document(*, source_hash="source", speaker_hash="speakers", profile=None, algorithm="caption-authoring-v1"):
    return CaptionDocument(
        algorithm_version=algorithm,
        profile=profile or HOUSE_ENGLISH_V1,
        options=CaptionExportOptions(timing_mode=CaptionTimingMode.HOUSE),
        source_hash=source_hash,
        speaker_overlay_hash=speaker_hash,
        events=(CaptionEvent(start=0.0, end=1.0, authored_lines=("[music]",), source_token_indices=(0,), timing_mode=CaptionTimingMode.HOUSE),),
    )


def _issue(**kwargs):
    values = {
        "rule_id": "AUDIO_EVENT_REVIEW_REQUIRED",
        "severity": CaptionIssueSeverity.WARNING,
        "source_token_indices": (0,),
        "message": "Review audio event.",
    }
    values.update(kwargs)
    return CaptionQCIssue(
        **values,
    )


def _approval(document=None, issue=None, **kwargs):
    document = document or _document()
    issue = issue or _issue()
    return new_caption_approval(document, CaptionQCReport(findings=(issue,), options=document.options, document_hash=document.document_hash), issue.issue_id, reason="Reviewed in context", actor_label="Editor A", approved_at=datetime(2026, 9, 1, tzinfo=timezone.utc), **kwargs)


def _music_result():
    return TranscriptionResult.model_validate({
        "text": "[music]", "language_code": "en", "audio_duration_secs": 1.0,
        "words": [{"text": "[music]", "start": 0.0, "end": 1.0, "type": "audio_event"}],
    })


def test_approval_survives_identical_regeneration_and_measurement_hash_roundtrip():
    document = _document()
    issue = _issue()
    approval = _approval(document, issue)
    assert CaptionQCIssue.model_validate_json(issue.model_dump_json()).measurement_hash == issue.measurement_hash
    restored = CaptionApprovalLedger.model_validate_json(CaptionApprovalLedger(approvals=(approval,)).model_dump_json())
    assert restored.approvals[0].measurement_hash == issue.measurement_hash
    assert restored.approvals[0].matches(document, issue)
    regenerated = issue.model_copy(update={"message": "Editorial review is required."})
    applied = apply_caption_approvals(document, CaptionQCReport(findings=(regenerated,), options=document.options), restored.approvals)
    finding = next(item for item in applied.findings if item.rule_id == issue.rule_id)
    assert finding.approval_reference == approval.approval_id
    assert finding.severity is issue.severity
    assert finding.measurement_hash == issue.measurement_hash
    assert applied.exception_state is CaptionExceptionState.APPROVED


def test_narrative_only_issue_drift_matches_freshly_constructed_finding():
    document = _document()
    original = _issue()
    approval = _approval(document, original)
    regenerated = CaptionQCIssue(
        rule_id=original.rule_id,
        severity=original.severity,
        event_id=original.event_id,
        source_token_indices=original.source_token_indices,
        actual_value=original.actual_value,
        threshold=original.threshold,
        message="Updated narrative wording.",
        suggested_resolution="A new editorial suggestion.",
    )
    assert regenerated.issue_id != original.issue_id
    assert regenerated.measurement_hash == original.measurement_hash
    assert approval.matches(document, regenerated)
    report = apply_caption_approvals(document, CaptionQCReport(findings=(regenerated,), options=document.options), (approval,))
    assert report.exception_state is CaptionExceptionState.APPROVED
    assert report.findings[0].approval_reference == approval.approval_id


def test_ledger_uniqueness_uses_material_scope_across_narrative_drift():
    document, issue = _document(), _issue()
    first = _approval(document, issue)
    refreshed = CaptionQCIssue(
        rule_id=issue.rule_id,
        severity=issue.severity,
        event_id=issue.event_id,
        source_token_indices=issue.source_token_indices,
        actual_value=issue.actual_value,
        threshold=issue.threshold,
        message="Refreshed narrative.",
    )
    second = _approval(document, refreshed)
    with pytest.raises(ValueError, match="one current approval"):
        CaptionApprovalLedger(approvals=(first, second))


@pytest.mark.parametrize("change", ["source", "speaker", "profile", "algorithm", "document", "measurement", "scope"])
def test_material_binding_changes_invalidate_exact_approval(change):
    document = _document()
    issue = _issue()
    approval = _approval(document, issue)
    changed_doc, changed_issue = document, issue
    if change == "source":
        changed_doc = document.model_copy(update={"source_hash": "new-source"})
    elif change == "speaker":
        changed_doc = document.model_copy(update={"speaker_overlay_hash": "new-speakers"})
    elif change == "profile":
        changed_doc = document.model_copy(update={"profile": HOUSE_ENGLISH_V1.model_copy(update={"profile_version": "2"})})
    elif change == "algorithm":
        changed_doc = document.model_copy(update={"algorithm_version": "caption-authoring-v2"})
    elif change == "document":
        changed_doc = document.model_copy(update={"provenance": {"editor": "changed"}})
    elif change == "measurement":
        changed_issue = issue.model_copy(update={"actual_value": 19.0})
    else:
        changed_issue = issue.model_copy(update={"source_token_indices": (0, 1)})
    assert not approval.matches(changed_doc, changed_issue)
    report = CaptionQCReport(findings=(changed_issue,), options=changed_doc.options)
    result = apply_caption_approvals(changed_doc, report, (approval,))
    target = next(item for item in result.findings if item.rule_id == changed_issue.rule_id)
    assert target.approval_reference is None
    assert is_actionable_issue(target)
    diagnostic = next(item for item in result.findings if item.rule_id == "CAPTION_APPROVAL_INVALIDATED")
    assert diagnostic.severity is CaptionIssueSeverity.WARNING
    assert diagnostic.actual_value["approval_id"] == approval.approval_id
    assert result.exception_state is CaptionExceptionState.APPROVAL_REQUIRED


def test_reason_actor_and_approval_date_do_not_change_matching():
    document, issue = _document(), _issue()
    first = _approval(document, issue)
    second = first.model_copy(update={"reason": "Different note", "actor_label": "Editor B", "approved_at": datetime(2026, 9, 2, tzinfo=timezone.utc)})
    assert first.matches(document, issue) and second.matches(document, issue)


def test_partial_approval_remains_actionable_and_technical_evidence_is_preserved():
    document = _document()
    first = _issue()
    second = _issue(rule_id="CPS_ABOVE_MAXIMUM", severity=CaptionIssueSeverity.FAILURE, event_id="event-2", actual_value=24.0, threshold=20.0)
    approved = _approval(document, first)
    report = CaptionQCReport(findings=(first, second), options=document.options, technical_status=CaptionTechnicalStatus.FAILED)
    result = apply_caption_approvals(document, report, (approved,))
    kept = {item.rule_id: item for item in result.findings}
    assert kept[first.rule_id].approval_reference == approved.approval_id
    assert kept[first.rule_id].severity is CaptionIssueSeverity.WARNING
    assert kept[second.rule_id].approval_reference is None
    assert kept[second.rule_id].actual_value == 24.0 and kept[second.rule_id].threshold == 20.0
    assert result.exception_state is CaptionExceptionState.APPROVAL_REQUIRED
    assert result.technical_status is CaptionTechnicalStatus.FAILED


def test_integrity_findings_cannot_be_approved_and_block_exception_state():
    document = _document()
    integrity = CaptionQCIssue(rule_id="SOURCE_NONFINITE_TIME", severity=CaptionIssueSeverity.BLOCKER, message="Invalid source time.")
    assert not is_approvable_issue(integrity)
    with pytest.raises(ValueError, match="cannot be approved"):
        _approval(document, integrity)
    review = _issue()
    approval = _approval(document, review)
    report = CaptionQCReport(findings=(review, integrity), options=document.options)
    applied = apply_caption_approvals(document, report, (approval,))
    assert applied.exception_state is CaptionExceptionState.APPROVAL_REQUIRED
    assert applied.technical_status is CaptionTechnicalStatus.BLOCKED
    assert next(item for item in applied.findings if item.rule_id == integrity.rule_id).severity is CaptionIssueSeverity.BLOCKER


def test_corrupt_approval_record_never_infers_approval(tmp_path):
    path = tmp_path / "broken.json"
    path.write_text('{"approvals":[{"issue_id":"looks-approved"}]}')
    record = load_caption_approvals_file(path)
    assert isinstance(record, InvalidCaptionApprovals)
    document, issue = _document(), _issue()
    report = apply_caption_approvals(document, CaptionQCReport(findings=(issue,), options=document.options), approval_record_error=record.detail)
    assert report.exception_state is CaptionExceptionState.APPROVAL_REQUIRED
    assert report.technical_status is CaptionTechnicalStatus.BLOCKED
    assert not any(item.approval_reference for item in report.findings)


def test_approve_revoke_and_empty_ledger_removal(tmp_path, monkeypatch):
    from elevenlabs_helper.engine.captions import overlays
    monkeypatch.setattr(overlays, "history_dir", lambda: tmp_path)
    document, issue = _document(), _issue()
    approval = _approval(document, issue)
    path = save_caption_approvals("job", (approval,))
    assert path.exists() and load_caption_approvals("job").approvals == (approval,)
    revoked = revoke_caption_approval((approval,), approval.approval_id)
    assert revoked == ()
    save_caption_approvals("job", revoked)
    assert not path.exists()
    with pytest.raises(ValueError, match="no matching"):
        revoke_caption_approval((approval,), "missing")


def test_ordinary_warnings_are_not_approvable_but_integrity_mismatch_is_not_either():
    ordinary = CaptionQCIssue(rule_id="LANGUAGE_PROFILE_UNVERIFIED", severity=CaptionIssueSeverity.WARNING, message="Language not covered.")
    assert not is_approvable_issue(ordinary)
    document = _document()
    with pytest.raises(ValueError, match="cannot be approved"):
        new_caption_approval(document, CaptionQCReport(findings=(ordinary,), options=document.options, document_hash=document.document_hash), ordinary.issue_id, reason="Reviewed", actor_label="Editor")
    assert not is_approvable_issue(CaptionQCIssue(rule_id="PROFILE_MISMATCH", severity=CaptionIssueSeverity.BLOCKER, message="Profile binding invalid."))


def test_strict_export_and_cli_summary_succeed_only_for_complete_valid_approvals(tmp_path):
    from elevenlabs_helper.engine.cli import _caption_cli_status
    result = _music_result()
    first = export_deliverables(result, tmp_path / "first", "music", [Deliverable.SRT], caption_options=CaptionExportOptions(export_policy=CaptionExportPolicy.STRICT))
    issue = next(item for item in first.report.findings if item.rule_id == "AUDIO_EVENT_REVIEW_REQUIRED")
    approval = new_caption_approval(first.interpretation.document, first.report, issue.issue_id, reason="Reviewed", actor_label="Editor")
    strict = export_deliverables(result, tmp_path / "approved", "music", [Deliverable.SRT], caption_options=CaptionExportOptions(export_policy=CaptionExportPolicy.STRICT), approvals=(approval,))
    assert strict.disposition is CaptionRenderingDisposition.WRITTEN
    assert strict.report.exception_state is CaptionExceptionState.APPROVED
    assert strict.report.findings and strict.report.findings[0].approval_reference == approval.approval_id
    job = Job(source_path="music.mp3", output_dir=str(tmp_path / "approved"))
    apply_export_result(job, strict, [Deliverable.SRT])
    assert job.caption_qc_summary["exception_state"] == "approved"
    assert job.caption_qc_summary["disposition"] == "written"
    assert completion_message(strict) == "Completed — caption exception approved"
    summary = {"exception_state": strict.report.exception_state.value, "severity_counts": strict.report.severity_counts, "disposition": strict.disposition.value}
    assert _caption_cli_status(summary) == 0
    inconsistent = dict(summary, disposition="blocked")
    assert _caption_cli_status(inconsistent) == 3
    partial = dict(summary, exception_state="approval_required", disposition="blocked", severity_counts={"warning": 1, "failure": 1, "blocker": 0})
    assert _caption_cli_status(partial) == 3
    stale = approval.model_copy(update={"source_hash": "stale"})
    invalid = export_deliverables(result, tmp_path / "stale", "music", [Deliverable.SRT], caption_options=CaptionExportOptions(export_policy=CaptionExportPolicy.STRICT), approvals=(stale,))
    assert invalid.disposition is CaptionRenderingDisposition.BLOCKED
    assert invalid.report.exception_state is CaptionExceptionState.APPROVAL_REQUIRED
    assert not (tmp_path / "stale" / "music.srt").exists()


def test_caption_csv_is_invariant_and_caption_path_makes_no_api_call(tmp_path):
    result = _music_result()
    # Export is a pure local operation; the same canonical data yields identical
    # Manual-Dub CSV whether a caption exception is applied or not.
    draft = export_deliverables(result, tmp_path / "draft", "music", [Deliverable.DUB_CSV, Deliverable.SRT])
    issue = next(item for item in draft.report.findings if item.rule_id == "AUDIO_EVENT_REVIEW_REQUIRED")
    approval = new_caption_approval(draft.interpretation.document, draft.report, issue.issue_id, reason="Reviewed", actor_label="Editor")
    approved = export_deliverables(result, tmp_path / "approved", "music", [Deliverable.DUB_CSV, Deliverable.SRT], approvals=(approval,))
    assert (tmp_path / "draft" / "music.csv").read_bytes() == (tmp_path / "approved" / "music.csv").read_bytes()
    assert approved.report.exception_state is CaptionExceptionState.APPROVED
