"""C3 authored-layout overlays stay source-bound and free to re-export."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from elevenlabs_helper.engine.captions import (
    HOUSE_ENGLISH_V1,
    CaptionContentKind,
    CaptionContext,
    CaptionBaselineCue,
    CaptionDocument,
    CaptionEvent,
    CaptionExportOptions,
    CaptionExportPolicy,
    CaptionOverlayOperation,
    CaptionOverlayOperationKind,
    CaptionSource,
    CaptionSourceToken,
    CaptionTimingMode,
    InvalidCaptionOverlay,
    apply_caption_overlay,
    load_caption_overlay,
    load_caption_overlay_file,
    new_caption_overlay,
    save_caption_overlay,
    validate_document,
)
from elevenlabs_helper.engine.captions.interpret import interpret_captions
from elevenlabs_helper.engine.exporters.writer import export_deliverables
from elevenlabs_helper.engine.config import Deliverable
from elevenlabs_helper.engine.config import EngineSettings
from elevenlabs_helper.engine.elevenlabs.models import TranscriptionResult
from elevenlabs_helper.engine.jobs.models import Job, JobStatus
from elevenlabs_helper.engine.jobs.store import JobStore
from elevenlabs_helper.engine.service import Engine
from tests.conftest import CANNED_RESULT


def _source() -> CaptionSource:
    return CaptionSource(
        tokens=(
            CaptionSourceToken(source_word_index=0, text="Hello", speaker_id="speaker_0", original_start=0.0, original_end=0.4),
            CaptionSourceToken(source_word_index=1, text="there", speaker_id="speaker_0", original_start=0.4, original_end=0.8),
            CaptionSourceToken(source_word_index=2, text="friend", speaker_id="speaker_0", original_start=0.8, original_end=1.2),
        ),
        speaker_overlay_hash="speaker-v1",
        language_code="en",
    )


def _document(*, mode: CaptionTimingMode = CaptionTimingMode.HOUSE) -> CaptionDocument:
    source = _source()
    return CaptionDocument(
        profile=HOUSE_ENGLISH_V1,
        options=CaptionExportOptions(timing_mode=mode),
        source_hash=source.source_hash,
        speaker_overlay_hash=source.speaker_overlay_hash,
        events=(
            CaptionEvent(
                start=0.0,
                end=1.2,
                authored_lines=("Hello there friend",),
                source_token_indices=(0, 1, 2),
                speaker_id="speaker_0",
                timing_mode=mode,
            ),
        ),
    )


def test_line_break_round_trip_is_source_bound_and_revalidated(tmp_path, monkeypatch):
    import elevenlabs_helper.engine.captions.overlays as overlays

    monkeypatch.setattr(overlays, "history_dir", lambda: tmp_path)
    document = _document()
    operation = CaptionOverlayOperation(
        kind=CaptionOverlayOperationKind.LINE_BREAK,
        source_token_indices=(0, 1, 2),
        authored_lines=("Hello there", "friend"),
    )
    overlay = new_caption_overlay(document, (operation,))
    save_caption_overlay("job-1", overlay)

    restored = load_caption_overlay("job-1")
    assert restored == overlay
    applied = apply_caption_overlay(document, _source(), None, restored)
    assert applied.applied is True
    assert applied.review_required is False
    assert applied.document.events[0].authored_lines == ("Hello there", "friend")
    assert applied.document.events[0].start == 0.0  # source anchored


def test_wording_edits_are_rejected_and_original_document_survives():
    document = _document()
    overlay = new_caption_overlay(
        document,
        (
            CaptionOverlayOperation(
                kind=CaptionOverlayOperationKind.LINE_BREAK,
                source_token_indices=(0, 1, 2),
                authored_lines=("Hello changed", "friend"),
            ),
        ),
    )

    applied = apply_caption_overlay(document, _source(), None, overlay)
    assert applied.applied is False
    assert applied.review_required is True
    assert applied.document == document
    assert applied.findings[0].rule_id == "CAPTION_OVERLAY_WORDING_CHANGE_FORBIDDEN"


def test_split_and_merge_are_disabled_in_source_mode_but_line_break_preserves_times():
    document = _document(mode=CaptionTimingMode.SOURCE)
    structural = new_caption_overlay(
        document,
        (
            CaptionOverlayOperation(
                kind=CaptionOverlayOperationKind.SPLIT,
                source_token_indices=(0,),
                authored_lines=("Hello",),
            ),
        ),
    )
    rejected = apply_caption_overlay(document, _source(), None, structural)
    assert rejected.applied is False
    assert rejected.findings[0].rule_id == "CAPTION_OVERLAY_STRUCTURE_DISABLED_SOURCE_MODE"

    line_break = new_caption_overlay(
        document,
        (
            CaptionOverlayOperation(
                kind=CaptionOverlayOperationKind.LINE_BREAK,
                source_token_indices=(0, 1, 2),
                authored_lines=("Hello there", "friend"),
            ),
        ),
    )
    applied = apply_caption_overlay(document, _source(), None, line_break)
    assert applied.applied is True
    assert [(event.start, event.end) for event in applied.document.events] == [(0.0, 1.2)]


def test_source_mode_layout_operations_must_cover_one_complete_existing_cue():
    source = _source()
    options = CaptionExportOptions(timing_mode=CaptionTimingMode.SOURCE)
    document = CaptionDocument(
        profile=HOUSE_ENGLISH_V1,
        options=options,
        source_hash=source.source_hash,
        speaker_overlay_hash=source.speaker_overlay_hash,
        events=(
            CaptionEvent(start=0.0, end=0.8, authored_lines=("Hello there",), source_token_indices=(0, 1), speaker_id="speaker_0", timing_mode=CaptionTimingMode.SOURCE),
            CaptionEvent(start=0.8, end=1.2, authored_lines=("friend",), source_token_indices=(2,), speaker_id="speaker_0", timing_mode=CaptionTimingMode.SOURCE),
        ),
    )
    partial = new_caption_overlay(
        document,
        (CaptionOverlayOperation(kind=CaptionOverlayOperationKind.LINE_BREAK, source_token_indices=(0,), authored_lines=("Hello",)),),
    )
    multiple = new_caption_overlay(
        document,
        (CaptionOverlayOperation(kind=CaptionOverlayOperationKind.LINE_BREAK, source_token_indices=(0, 1, 2), authored_lines=("Hello there", "friend")),),
    )
    for overlay in (partial, multiple):
        applied = apply_caption_overlay(document, source, None, overlay)
        assert applied.applied is False
        assert applied.findings[0].rule_id == "CAPTION_OVERLAY_SOURCE_MODE_RANGE_INVALID"


def test_house_overlay_timing_uses_profile_and_program_caps_then_qc_reports_impossible_case():
    source = CaptionSource(
        tokens=(CaptionSourceToken(source_word_index=0, text="abcdefghijklmnopqrst", original_start=0.0, original_end=0.2),),
        language_code="en",
    )
    profile = HOUSE_ENGLISH_V1.model_copy(update={"max_duration_secs": 1.1})
    document = CaptionDocument(
        profile=profile,
        options=CaptionExportOptions(timing_mode=CaptionTimingMode.HOUSE),
        source_hash=source.source_hash,
        speaker_overlay_hash=source.speaker_overlay_hash,
        events=(CaptionEvent(start=0.0, end=1.0, authored_lines=("abcdefghijklmnopqrst",), source_token_indices=(0,), timing_mode=CaptionTimingMode.HOUSE),),
    )
    overlay = new_caption_overlay(
        document,
        (CaptionOverlayOperation(kind=CaptionOverlayOperationKind.LINE_BREAK, source_token_indices=(0,), authored_lines=("abcdefghijklmnopqrst",)),),
    )
    profile_capped = apply_caption_overlay(document, source, None, overlay)
    assert profile_capped.applied is True
    assert profile_capped.document.events[0].end == 1.1

    program_capped = apply_caption_overlay(document, source, CaptionContext(duration_secs=0.9), overlay)
    assert program_capped.document.events[0].end == 0.9
    report = validate_document(program_capped.document, source, profile, CaptionContext(duration_secs=0.9))
    assert any(item.rule_id == "DURATION_BELOW_MINIMUM" for item in report.findings)


def test_house_overlay_retains_speech_exceeds_timing_bound_diagnostic_after_revalidation():
    source = CaptionSource(
        tokens=(CaptionSourceToken(source_word_index=0, text="Hello", original_start=0.0, original_end=2.0),),
        baseline_cues=(CaptionBaselineCue(index=1, text="Hello", start=0.0, end=2.0, source_word_indices=(0,)),),
        language_code="en",
    )
    options = CaptionExportOptions(timing_mode=CaptionTimingMode.HOUSE)
    context = CaptionContext(duration_secs=0.9)
    base = interpret_captions(source, options, context)
    event = base.document.events[0]
    overlay = new_caption_overlay(
        base.document,
        (CaptionOverlayOperation(kind=CaptionOverlayOperationKind.LINE_BREAK, source_token_indices=event.source_token_indices, authored_lines=event.authored_lines),),
    )

    reapplied = interpret_captions(source, options, context, overlay)
    finding = next(item for item in reapplied.report.findings if item.rule_id == "SPEECH_EXCEEDS_TIMING_BOUND")
    assert finding.source_token_indices == (0,)
    assert finding.actual_value["bound"] == "program_end"
    assert reapplied.report.technical_status.value == "failed"


def test_stale_source_speaker_profile_or_algorithm_binding_requires_review():
    document = _document()
    overlay = new_caption_overlay(
        document,
        (
            CaptionOverlayOperation(
                kind=CaptionOverlayOperationKind.LINE_BREAK,
                source_token_indices=(0, 1, 2),
                authored_lines=("Hello there", "friend"),
            ),
        ),
    ).model_copy(update={"speaker_overlay_hash": "changed-speakers"})

    applied = apply_caption_overlay(document, _source(), None, overlay)
    assert applied.applied is False
    assert applied.review_required is True
    assert applied.findings[0].rule_id == "CAPTION_OVERLAY_REVIEW_REQUIRED"


def test_house_split_uses_only_source_anchored_boundaries_and_complete_ledger():
    document = _document()
    overlay = new_caption_overlay(
        document,
        (
            CaptionOverlayOperation(
                kind=CaptionOverlayOperationKind.SPLIT,
                source_token_indices=(0, 1),
                authored_lines=("Hello there",),
            ),
            CaptionOverlayOperation(
                kind=CaptionOverlayOperationKind.SPLIT,
                source_token_indices=(2,),
                authored_lines=("friend",),
            ),
        ),
    )
    applied = apply_caption_overlay(document, _source(), None, overlay)
    assert applied.applied is True
    assert [event.source_token_indices for event in applied.document.events] == [(0, 1), (2,)]
    assert applied.document.events[0].start == 0.0
    assert applied.document.events[1].start == 0.8


def test_house_merge_rejects_distinct_dialogue_speakers_but_allows_one_speaker():
    source = CaptionSource(
        tokens=(
            CaptionSourceToken(source_word_index=0, text="Hello", speaker_id="speaker_0", original_start=0.0, original_end=0.5),
            CaptionSourceToken(source_word_index=1, text="there", speaker_id="speaker_1", original_start=0.5, original_end=1.0),
        ),
        speaker_overlay_hash="speaker-v1",
        language_code="en",
    )
    document = CaptionDocument(
        profile=HOUSE_ENGLISH_V1,
        options=CaptionExportOptions(timing_mode=CaptionTimingMode.HOUSE),
        source_hash=source.source_hash,
        speaker_overlay_hash=source.speaker_overlay_hash,
        events=(
            CaptionEvent(start=0.0, end=0.5, authored_lines=("Hello",), source_token_indices=(0,), speaker_id="speaker_0", timing_mode=CaptionTimingMode.HOUSE),
            CaptionEvent(start=0.5, end=1.0, authored_lines=("there",), source_token_indices=(1,), speaker_id="speaker_1", timing_mode=CaptionTimingMode.HOUSE),
        ),
    )
    operation = CaptionOverlayOperation(
        kind=CaptionOverlayOperationKind.MERGE,
        source_token_indices=(0, 1),
        authored_lines=("Hello there",),
    )

    rejected = apply_caption_overlay(document, source, None, new_caption_overlay(document, (operation,)))
    assert rejected.applied is False
    assert rejected.review_required is True
    assert rejected.findings[0].rule_id == "CAPTION_OVERLAY_MULTI_SPEAKER_MERGE_INVALID"
    assert rejected.findings[0].actual_value == {"speaker_ids": ["speaker_0", "speaker_1"]}

    same_speaker_source = source.model_copy(
        update={
            "tokens": tuple(
                token.model_copy(update={"speaker_id": "speaker_0"})
                for token in source.tokens
            )
        }
    )
    same_speaker_document = document.model_copy(
        update={
            "source_hash": same_speaker_source.source_hash,
            "events": tuple(
                event.model_copy(update={"speaker_id": "speaker_0"})
                for event in document.events
            ),
        }
    )
    allowed = apply_caption_overlay(
        same_speaker_document,
        same_speaker_source,
        None,
        new_caption_overlay(same_speaker_document, (operation,)),
    )
    assert allowed.applied is True
    assert allowed.document.events[0].speaker_id == "speaker_0"

    partially_unknown_source = source.model_copy(
        update={
            "tokens": (
                source.tokens[0],
                source.tokens[1].model_copy(update={"speaker_id": None}),
            )
        }
    )
    partially_unknown_document = document.model_copy(
        update={
            "source_hash": partially_unknown_source.source_hash,
            "events": (
                document.events[0],
                document.events[1].model_copy(update={"speaker_id": None}),
            ),
        }
    )
    partially_unknown = apply_caption_overlay(
        partially_unknown_document,
        partially_unknown_source,
        None,
        new_caption_overlay(partially_unknown_document, (operation,)),
    )
    assert partially_unknown.applied is False
    assert partially_unknown.findings[0].rule_id == "CAPTION_OVERLAY_MULTI_SPEAKER_MERGE_INVALID"
    assert partially_unknown.findings[0].actual_value == {
        "speaker_ids": ["<unknown>", "speaker_0"]
    }


def test_sfx_operation_can_only_reference_audio_event_source():
    document = _document()
    overlay = new_caption_overlay(
        document,
        (
            CaptionOverlayOperation(
                kind=CaptionOverlayOperationKind.SFX,
                source_token_indices=(0,),
                authored_lines=("Hello",),
            ),
        ),
    )
    applied = apply_caption_overlay(document, _source(), None, overlay)
    assert applied.applied is False
    assert applied.findings[0].rule_id == "CAPTION_OVERLAY_SFX_REFERENCE_INVALID"


def test_corrupt_recorded_overlay_is_reported_not_silently_dropped(tmp_path, monkeypatch):
    import elevenlabs_helper.engine.captions.overlays as overlays

    monkeypatch.setattr(overlays, "history_dir", lambda: tmp_path)
    overlays.caption_overlay_path("job-corrupt").write_text("{not-json", encoding="utf-8")
    overlay = load_caption_overlay("job-corrupt")
    assert isinstance(overlay, InvalidCaptionOverlay)

    interpretation = interpret_captions(_source(), _document().options, overlay=overlay)
    assert any(item.rule_id == "CAPTION_OVERLAY_INVALID" for item in interpretation.report.findings)


@pytest.mark.parametrize("missing_binding", ["schema_version", "algorithm_version"])
def test_serialized_overlay_requires_explicit_version_bindings_and_strict_blocks(
    tmp_path, missing_binding
):
    document = _document()
    operation = CaptionOverlayOperation(
        kind=CaptionOverlayOperationKind.LINE_BREAK,
        source_token_indices=(0, 1, 2),
        authored_lines=("Hello there", "friend"),
    )
    payload = new_caption_overlay(document, (operation,)).model_dump(mode="json")
    payload.pop(missing_binding)
    path = tmp_path / f"missing-{missing_binding}.caption-overlay.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    invalid = load_caption_overlay_file(path)
    assert isinstance(invalid, InvalidCaptionOverlay)
    assert missing_binding in invalid.detail

    result = TranscriptionResult.model_validate(CANNED_RESULT)
    exported = export_deliverables(
        result,
        tmp_path / missing_binding,
        "clip",
        [Deliverable.SRT],
        caption_options=CaptionExportOptions(
            timing_mode=CaptionTimingMode.HOUSE,
            export_policy=CaptionExportPolicy.STRICT,
        ),
        overlay=invalid,
    )
    assert exported.disposition.value == "blocked"
    assert "srt" not in exported.paths


def test_invalid_explicit_overlay_requires_review_and_strict_blocks_caption_replacement(tmp_path):
    result = TranscriptionResult.model_validate(CANNED_RESULT)
    invalid = InvalidCaptionOverlay(detail="overlay JSON was corrupt")
    exported = export_deliverables(
        result,
        tmp_path,
        "clip",
        [Deliverable.SRT],
        caption_options=CaptionExportOptions(
            timing_mode=CaptionTimingMode.HOUSE,
            export_policy=CaptionExportPolicy.STRICT,
        ),
        overlay=invalid,
    )
    assert exported.disposition.value == "blocked"
    assert "srt" not in exported.paths
    assert exported.report.editorial_coverage.value == "approval_required"


def test_overlay_reexport_keeps_manual_dub_csv_byte_for_byte(tmp_path):
    result = TranscriptionResult.model_validate(CANNED_RESULT)
    options = CaptionExportOptions(timing_mode=CaptionTimingMode.HOUSE)
    original = export_deliverables(
        result,
        tmp_path / "original",
        "clip",
        [Deliverable.SRT, Deliverable.DUB_CSV],
        caption_options=options,
    )
    document = original.interpretation.document
    event = document.events[0]
    overlay = new_caption_overlay(
        document,
        (
            CaptionOverlayOperation(
                kind=CaptionOverlayOperationKind.LINE_BREAK,
                source_token_indices=event.source_token_indices,
                authored_lines=event.authored_lines,
            ),
        ),
    )
    reexported = export_deliverables(
        result,
        tmp_path / "reexported",
        "clip",
        [Deliverable.SRT, Deliverable.DUB_CSV],
        caption_options=options,
        overlay=overlay,
    )
    assert Path(original.paths["dub_csv"]).read_bytes() == Path(reexported.paths["dub_csv"]).read_bytes()


def test_job_overlay_survives_restart_and_reexports_without_transcription(tmp_path, monkeypatch):
    import elevenlabs_helper.engine.captions.overlays as overlays

    overlay_dir = tmp_path / "history"
    overlay_dir.mkdir()
    monkeypatch.setattr(overlays, "history_dir", lambda: overlay_dir)
    result = TranscriptionResult.model_validate(CANNED_RESULT)
    history = tmp_path / "saved-result.json"
    history.write_text(result.model_dump_json(), encoding="utf-8")
    database = tmp_path / "jobs.db"
    output = tmp_path / "out"
    job = Job(
        source_path=str(tmp_path / "clip.mp3"),
        output_dir=str(output),
        deliverables=[Deliverable.SRT, Deliverable.DUB_CSV],
        status=JobStatus.DONE,
        history_json=str(history),
        staged_caption_options=CaptionExportOptions(timing_mode=CaptionTimingMode.HOUSE),
    )
    first = Engine(settings=EngineSettings(output_root=output), store=JobStore(db_path=database))
    try:
        first.store.upsert(job)
        initial = first.reexport(job.id)
        document = CaptionDocument.model_validate_json(Path(initial["caption_document"]).read_text())
        event = document.events[0]
        first.save_caption_overlay(
            job.id,
            new_caption_overlay(
                document,
                (
                    CaptionOverlayOperation(
                        kind=CaptionOverlayOperationKind.LINE_BREAK,
                        source_token_indices=event.source_token_indices,
                        authored_lines=event.authored_lines,
                    ),
                ),
            ),
        )
        before = Path(initial["dub_csv"]).read_bytes()
    finally:
        first.stop()

    restarted = Engine(settings=EngineSettings(output_root=output), store=JobStore(db_path=database))
    try:
        after = restarted.reexport(job.id)
        assert Path(after["dub_csv"]).read_bytes() == before
        assert load_caption_overlay(job.id) is not None
    finally:
        restarted.stop()


def test_engine_saves_source_line_break_while_unrelated_failure_remains_visible(tmp_path):
    payload = dict(CANNED_RESULT)
    payload["text"] = "abcdefghijklmnop qrstuvwxyzabcdef"
    payload["words"] = [
        {"text": "abcdefghijklmnop", "start": 0.0, "end": 0.2, "type": "word", "speaker_id": "speaker_0"},
        {"text": "qrstuvwxyzabcdef", "start": 0.2, "end": 0.4, "type": "word", "speaker_id": "speaker_0"},
    ]
    result = TranscriptionResult.model_validate(payload)
    history = tmp_path / "result.json"
    history.write_text(result.model_dump_json(), encoding="utf-8")
    store = JobStore(db_path=tmp_path / "jobs.db")
    engine = Engine(settings=EngineSettings(output_root=tmp_path / "out"), store=store)
    job = Job(
        source_path=str(tmp_path / "clip.mp3"),
        output_dir=str(tmp_path / "out"),
        deliverables=[Deliverable.SRT],
        status=JobStatus.DONE,
        history_json=str(history),
        staged_caption_options=CaptionExportOptions(timing_mode=CaptionTimingMode.SOURCE),
    )
    try:
        store.upsert(job)
        initial = engine.reexport(job.id)
        document = CaptionDocument.model_validate_json(Path(initial["caption_document"]).read_text())
        event = document.events[0]
        assert event.end == 0.4
        overlay = new_caption_overlay(
            document,
            (CaptionOverlayOperation(
                kind=CaptionOverlayOperationKind.LINE_BREAK,
                source_token_indices=event.source_token_indices,
                authored_lines=("abcdefghijklmnop", "qrstuvwxyzabcdef"),
            ),),
        )
        engine.save_caption_overlay(job.id, overlay)
        reapplied = engine.reexport(job.id)
        saved_document = CaptionDocument.model_validate_json(
            Path(reapplied["caption_document"]).read_text()
        )
        report = json.loads(Path(reapplied["caption_qc"]).read_text())

        assert engine.get_caption_overlay(job.id) == overlay
        assert saved_document.events[0].authored_lines == (
            "abcdefghijklmnop",
            "qrstuvwxyzabcdef",
        )
        assert saved_document.events[0].start == 0.0
        assert saved_document.events[0].end == 0.4
        assert report["technical_status"] == "failed"
        assert any(
            finding["rule_id"] in {"CPS_ABOVE_MAXIMUM", "DURATION_BELOW_MINIMUM"}
            for finding in report["findings"]
        )
    finally:
        engine.stop()
