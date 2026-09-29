from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import threading
import time

import pytest
import csv
import io

from elevenlabs_helper.engine.captions import (
    CaptionEvent,
    CaptionExportOptions,
    CaptionIssueSeverity,
    CaptionQCIssue,
    CaptionQCReport,
    CaptionOverlayOperation,
    CaptionOverlayOperationKind,
    CaptionQCReport,
    CaptionTimingMode,
    HOUSE_ENGLISH_V1,
    new_caption_approval,
    new_caption_overlay,
    save_caption_approvals,
    save_caption_overlay,
)
from elevenlabs_helper.engine.captions.models import CaptionDocument, CaptionQCIssue
from elevenlabs_helper.engine.config import Deliverable, EngineSettings
from elevenlabs_helper.engine.edits import SpeakerEdits, edits_path, save_edits
from elevenlabs_helper.engine.elevenlabs.models import TranscriptionResult
from elevenlabs_helper.engine.history import (
    delete_history_group,
    history_dir,
    history_path,
    prune_history_groups,
)
from elevenlabs_helper.engine.jobs.store import JobStore
from elevenlabs_helper.engine.jobs.models import JobStatus
from elevenlabs_helper.engine.service import Engine, ReexportError, make_job


def _result():
    return TranscriptionResult.model_validate({
        "text": "[music]", "language_code": "en", "audio_duration_secs": 1.0,
        "words": [{"text": "[music]", "start": 0.0, "end": 1.0, "type": "audio_event"}],
    })


def _dialogue_result():
    return TranscriptionResult.model_validate({
        "text": "Hello Hi", "language_code": "en", "audio_duration_secs": 2.0,
        "words": [
            {"text": "Hello", "start": 0.0, "end": 1.0, "type": "word", "speaker_id": "speaker_0"},
            {"text": "Hi", "start": 1.0, "end": 2.0, "type": "word", "speaker_id": "speaker_1"},
        ],
    })


def _document():
    return CaptionDocument(
        profile=HOUSE_ENGLISH_V1,
        options=CaptionExportOptions(timing_mode=CaptionTimingMode.HOUSE),
        source_hash="src", speaker_overlay_hash="speaker",
        events=(CaptionEvent(start=0.0, end=1.0, authored_lines=("[music]",), source_token_indices=(0,), timing_mode=CaptionTimingMode.HOUSE),),
    )


def _private_dir(tmp_path, monkeypatch):
    from elevenlabs_helper.engine import config
    monkeypatch.setattr(config, "app_support_dir", lambda: tmp_path / "app")
    return history_dir()


def test_permanent_delete_removes_private_group_and_job_but_preserves_user_output(tmp_path, monkeypatch):
    private = _private_dir(tmp_path, monkeypatch)
    result = _result()
    history_path("job-1").write_text(result.model_dump_json())
    save_edits("job-1", SpeakerEdits(speaker_names={"speaker_0": "MARA"}))
    operation = CaptionOverlayOperation(kind=CaptionOverlayOperationKind.SFX, source_token_indices=(0,), authored_lines=("[music]",))
    save_caption_overlay("job-1", new_caption_overlay(_document(), (operation,)))
    finding = CaptionQCIssue(rule_id="AUDIO_EVENT_REVIEW_REQUIRED", severity=CaptionIssueSeverity.WARNING, message="Review.")
    document = _document()
    report = CaptionQCReport(findings=(finding,), options=document.options, document_hash=document.document_hash)
    approval = new_caption_approval(document, report, finding.issue_id, reason="Reviewed", actor_label="Editor")
    save_caption_approvals("job-1", (approval,))

    output = tmp_path / "user-output"
    output.mkdir()
    user_file = output / "deliverable.srt"
    user_file.write_text("user-owned caption output")
    settings = EngineSettings(output_root=output)
    store = JobStore(db_path=tmp_path / "jobs.db")
    source = tmp_path / "clip.mp3"
    source.write_bytes(b"user source")
    job = make_job(source, settings)
    job.id = "job-1"
    job.output_dir = str(output)
    store.upsert(job)
    engine = Engine(settings=settings, store=store)

    engine.delete_permanently(job.id)

    assert store.get(job.id) is None
    assert not any((private / f"job-1{suffix}").exists() for suffix in (".json", ".edits.json", ".caption-overlay.json", ".caption-approvals.json"))
    assert user_file.read_text() == "user-owned caption output"
    store.close()


def test_age_pruning_removes_only_aged_managed_groups(tmp_path, monkeypatch):
    private = _private_dir(tmp_path, monkeypatch)
    result = _result()
    for job_id in ("old", "new"):
        history_path(job_id).write_text(result.model_dump_json())
        save_edits(job_id, SpeakerEdits(speaker_names={"speaker_0": "MARA"}))
        document = _document()
        operation = CaptionOverlayOperation(kind=CaptionOverlayOperationKind.SFX, source_token_indices=(0,), authored_lines=("[music]",))
        save_caption_overlay(job_id, new_caption_overlay(document, (operation,)))
        finding = CaptionQCIssue(rule_id="AUDIO_EVENT_REVIEW_REQUIRED", severity=CaptionIssueSeverity.WARNING, message="Review.")
        report = CaptionQCReport(findings=(finding,), options=document.options, document_hash=document.document_hash)
        save_caption_approvals(job_id, (new_caption_approval(document, report, finding.issue_id, reason="Checked", actor_label="Editor"),))
    stamp = time.time() - 40 * 86400
    os.utime(history_path("old"), (stamp, stamp))
    output = tmp_path / "deliveries"
    output.mkdir()
    external = output / "orphan.caption-approvals.json"
    external.write_text("must remain")

    removed = prune_history_groups(30)

    assert removed == {"old"}
    assert not history_path("old").exists() and not edits_path("old").exists()
    assert not any((private / f"old{suffix}").exists() for suffix in (".caption-overlay.json", ".caption-approvals.json"))
    assert history_path("new").exists() and edits_path("new").exists()
    assert (private / "new.caption-overlay.json").exists() and (private / "new.caption-approvals.json").exists()
    assert external.read_text() == "must remain"


def test_orphan_cleanup_runs_when_retention_disabled_and_only_in_private_history(tmp_path, monkeypatch):
    private = _private_dir(tmp_path, monkeypatch)
    orphans = [private / f"ghost{suffix}" for suffix in (".edits.json", ".caption-overlay.json", ".caption-approvals.json")]
    for path in orphans:
        path.write_text("orphan")
    canonical = history_path("keep-forever")
    canonical.write_text(_result().model_dump_json())
    output = tmp_path / "user-output"
    output.mkdir()
    external = output / "ghost.caption-overlay.json"
    external.write_text("user data")

    assert prune_history_groups(0) == set()
    assert all(not path.exists() for path in orphans)
    assert canonical.exists()
    assert external.read_text() == "user data"


def test_engine_retention_pruning_removes_expired_job_record(tmp_path, monkeypatch):
    _private_dir(tmp_path, monkeypatch)
    source = tmp_path / "old.mp3"
    source.write_bytes(b"source")
    settings = EngineSettings(output_root=tmp_path / "out", history_retention_days=30)
    store = JobStore(db_path=tmp_path / "retention.db")
    job = make_job(source, settings)
    job.id = "expired-job"
    job.history_json = str(history_path(job.id))
    history_path(job.id).write_text(_result().model_dump_json())
    stamp = time.time() - 40 * 86400
    os.utime(history_path(job.id), (stamp, stamp))
    store.upsert(job)

    Engine(settings=settings, store=store)

    assert store.get(job.id) is None
    assert not history_path(job.id).exists()
    store.close()


def test_history_off_keeps_approval_and_overlay_only_in_live_engine_when_input_exists(tmp_path, monkeypatch):
    private = _private_dir(tmp_path, monkeypatch)
    source = tmp_path / "clip.mp3"
    source.write_bytes(b"source")
    canonical_input = tmp_path / "canonical-input.json"
    canonical_input.write_text(_result().model_dump_json())
    output = tmp_path / "output"
    settings = EngineSettings(output_root=output, keep_history_json=False, deliverables=[Deliverable.SRT])
    store = JobStore(db_path=tmp_path / "jobs.db")
    job = make_job(source, settings)
    job.history_json = str(canonical_input)
    store.upsert(job)
    engine = Engine(settings=settings, store=store)
    current = engine._caption_interpretation(job)
    issue = next(item for item in current.report.findings if item.rule_id == "AUDIO_EVENT_REVIEW_REQUIRED")
    approval = engine.approve_caption_issue(job.id, issue.issue_id, reason="Reviewed locally", actor_label="Editor")
    assert engine.get_caption_approvals(job.id).approvals == (approval,)
    operation = CaptionOverlayOperation(kind=CaptionOverlayOperationKind.SFX, source_token_indices=(0,), authored_lines=current.document.events[0].authored_lines)
    overlay = new_caption_overlay(current.document, (operation,))
    engine._ephemeral_caption_overlays[job.id] = overlay
    engine.save_caption_overlay(job.id, overlay)
    assert engine.get_caption_overlay(job.id) == overlay
    assert not list(private.glob(f"{job.id}.caption-*.json"))

    restarted = Engine(settings=settings, store=store)
    assert restarted.get_caption_approvals(job.id) is None
    assert restarted.get_caption_overlay(job.id) is None
    engine.revoke_caption_approval(job.id, approval.approval_id)
    assert engine.get_caption_approvals(job.id).approvals == ()
    store.close()


def test_history_off_approval_has_clear_error_without_canonical_input(tmp_path, monkeypatch):
    _private_dir(tmp_path, monkeypatch)
    source = tmp_path / "missing.mp3"
    source.write_bytes(b"source")
    settings = EngineSettings(output_root=tmp_path / "out", keep_history_json=False)
    store = JobStore(db_path=tmp_path / "jobs.db")
    job = make_job(source, settings)
    store.upsert(job)
    engine = Engine(settings=settings, store=store)

    with pytest.raises(ReexportError, match="no canonical transcript history is available"):
        engine.approve_caption_issue(job.id, "missing-issue", reason="Reason", actor_label="Editor")
    operation = CaptionOverlayOperation(kind=CaptionOverlayOperationKind.LINE_BREAK, source_token_indices=(0,), authored_lines=("Hello",))
    with pytest.raises(ReexportError, match="No stored transcript found"):
        engine.save_caption_overlay(job.id, new_caption_overlay(_document(), (operation,)))
    assert not list(history_dir().glob(f"{job.id}.caption-*.json"))
    store.close()


def test_history_off_speaker_edits_are_ephemeral_and_used_by_reexport_and_csv(tmp_path, monkeypatch):
    private = _private_dir(tmp_path, monkeypatch)
    source = tmp_path / "dialogue.mp3"
    source.write_bytes(b"source")
    canonical_input = tmp_path / "dialogue-input.json"
    result = _dialogue_result()
    canonical_input.write_text(result.model_dump_json())
    settings = EngineSettings(output_root=tmp_path / "out", keep_history_json=False, deliverables=[Deliverable.DUB_CSV])
    store = JobStore(db_path=tmp_path / "speaker-edits.db")
    job = make_job(source, settings)
    job.history_json = str(canonical_input)
    store.upsert(job)
    engine = Engine(settings=settings, store=store)

    engine.save_speaker_edits(job.id, SpeakerEdits(speaker_names={"speaker_0": "MARA"}))
    assert engine.get_speaker_edits(job.id).speaker_names == {"speaker_0": "MARA"}
    assert engine.get_transcript(job.id).speaker_label("speaker_0") == "MARA"
    assert not edits_path(job.id).exists()
    artifacts = engine.reexport(job.id)
    rows = list(csv.reader(io.StringIO(artifacts["dub_csv"].read_text())))
    assert rows[1][0] == "MARA"

    restarted = Engine(settings=settings, store=store)
    assert restarted.get_speaker_edits(job.id).is_empty()
    assert restarted.get_transcript(job.id).speaker_label("speaker_0") == "Speaker 1"
    restarted_artifacts = restarted.reexport(job.id)
    after_restart = list(csv.reader(io.StringIO(restarted_artifacts["dub_csv"].read_text())))
    assert after_restart[1][0] == "Speaker 1"
    assert not edits_path(job.id).exists()

    import elevenlabs_helper.engine.processors.speech_to_text as processor_module
    processor_job = make_job(source, settings)
    processor_job.id = "processor-no-private-edit-load"
    processor_job.deliverables = [Deliverable.DUB_CSV]
    def forbidden_private_read(*_args, **_kwargs):
        raise AssertionError("history-off processor must not load private editing overlays")
    monkeypatch.setattr(processor_module, "load_edits", forbidden_private_read)
    monkeypatch.setattr(processor_module, "load_caption_overlay", forbidden_private_read)
    monkeypatch.setattr(processor_module, "load_caption_approvals", forbidden_private_read)
    from elevenlabs_helper.engine.processors.base import ProcessContext
    processor_module._export(processor_job, ProcessContext(api_key="", settings=settings), result, source)
    assert not edits_path(processor_job.id).exists()
    assert private.exists()
    store.close()


def test_history_off_normal_processor_hands_result_to_live_engine_only(
    tmp_path, monkeypatch, dummy_mp3
):
    import elevenlabs_helper.engine.processors.speech_to_text as processor_module

    private = _private_dir(tmp_path, monkeypatch)
    transcription_calls = 0

    def transcribe(*_args, **_kwargs):
        nonlocal transcription_calls
        transcription_calls += 1
        return _dialogue_result()

    monkeypatch.setattr(processor_module, "transcribe_file", transcribe)
    settings = EngineSettings(
        output_root=tmp_path / "out",
        keep_history_json=False,
        deliverables=[Deliverable.SRT, Deliverable.VTT],
        retry_base_delay_secs=0.01,
    )
    store = JobStore(db_path=tmp_path / "live-result.db")
    done = threading.Event()
    engine = Engine(
        settings=settings,
        store=store,
        on_update=lambda item: done.set() if item.status in {
            JobStatus.DONE,
            JobStatus.FAILED,
            JobStatus.CANCELED,
        } else None,
    )
    engine.queue._api_key_provider = lambda: "test-key"
    job = engine.add_source(dummy_mp3)
    engine.start()
    assert engine.run_staged() == 1
    assert done.wait(timeout=30), "history-off transcription did not finish"

    saved = store.get(job.id)
    assert saved is not None and saved.status is JobStatus.DONE, saved.error if saved else None
    assert saved.history_json is None
    assert (Path(saved.output_dir) / "sample.srt").exists()
    assert (Path(saved.output_dir) / "sample.vtt").exists()
    assert not list(private.glob(f"{job.id}*"))
    assert engine.has_reexport_source(job.id)

    engine.save_speaker_edits(
        job.id,
        SpeakerEdits(speaker_names={"speaker_0": "MARA"}),
    )
    assert engine.get_transcript(job.id).speaker_label("speaker_0") == "MARA"

    current = engine._caption_interpretation(saved)
    first_event = current.document.events[0]
    overlay = new_caption_overlay(
        current.document,
        (
            CaptionOverlayOperation(
                kind=CaptionOverlayOperationKind.LINE_BREAK,
                source_token_indices=first_event.source_token_indices,
                authored_lines=first_event.authored_lines,
            ),
        ),
    )
    engine.save_caption_overlay(job.id, overlay)
    with_overlay = engine._caption_interpretation(saved)
    review = next(
        finding
        for finding in with_overlay.report.findings
        if finding.rule_id == "SPEAKER_IDENTITY_REVIEW_REQUIRED"
    )
    approval = engine.approve_caption_issue(
        job.id,
        review.issue_id,
        reason="Speaker identities reviewed in the live session",
        actor_label="Editor",
    )
    assert engine.get_caption_overlay(job.id) == overlay
    assert engine.get_caption_approvals(job.id).approvals == (approval,)

    before_reexport_calls = transcription_calls
    regenerated = engine.reexport(job.id)
    assert {"srt", "vtt"}.issubset(regenerated)
    assert transcription_calls == before_reexport_calls == 1
    assert not list(private.glob(f"{job.id}*"))

    engine.stop()
    assert engine._ephemeral_results == {}
    assert engine._ephemeral_caption_overlays == {}
    assert engine._ephemeral_caption_approvals == {}
    assert engine._ephemeral_speaker_edits == {}

    restarted = Engine(settings=settings, store=store)
    try:
        with pytest.raises(ReexportError, match="No stored transcript found"):
            restarted.get_transcript(job.id)
        with pytest.raises(ReexportError, match="No stored transcript found"):
            restarted.reexport(job.id)
        assert not restarted.has_reexport_source(job.id)
        assert restarted.get_caption_overlay(job.id) is None
        assert restarted.get_caption_approvals(job.id) is None
        assert restarted.get_speaker_edits(job.id).is_empty()
    finally:
        restarted.stop()
        store.close()


def test_delete_group_does_not_follow_user_output_paths(tmp_path, monkeypatch):
    private = _private_dir(tmp_path, monkeypatch)
    history_path("one").write_text(_result().model_dump_json())
    out = tmp_path / "one.caption-approvals.json"
    out.write_text("unmanaged")
    delete_history_group("one")
    assert not history_path("one").exists()
    assert out.exists()
