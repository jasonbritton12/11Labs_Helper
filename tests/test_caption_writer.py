"""P06 caption batch and writer integration contracts."""

from __future__ import annotations

import json

import pytest

from elevenlabs_helper.engine.captions import (
    CaptionDocument,
    CaptionExportOptions,
    CaptionExportPolicy,
    CaptionQCReport,
    CaptionRenderingDisposition,
    CaptionTimingMode,
)
from elevenlabs_helper.engine.config import Deliverable
from elevenlabs_helper.engine.caption_jobs import completion_message
from elevenlabs_helper.engine.elevenlabs.models import TranscriptionResult
from elevenlabs_helper.engine.exporters import writer
from elevenlabs_helper.engine.exporters.writer import (
    ExportWriteError,
    deliverable_paths,
    export_deliverables,
    write_deliverables,
)


def _result(*, end: float = 1.0, text: str = "Hello world.") -> TranscriptionResult:
    return TranscriptionResult.model_validate(
        {
            "text": text,
            "language_code": "en",
            "audio_duration_secs": max(end, 1.0),
            "words": [
                {
                    "text": text,
                    "start": 0.0,
                    "end": end,
                    "type": "word",
                    "speaker_id": "speaker_0",
                }
            ],
        }
    )


def _audio_event_result() -> TranscriptionResult:
    return TranscriptionResult.model_validate(
        {
            "text": "[music]",
            "language_code": "en",
            "audio_duration_secs": 1.0,
            "words": [
                {
                    "text": "[music]",
                    "start": 0.0,
                    "end": 1.0,
                    "type": "audio_event",
                }
            ],
        }
    )


def _multi_speaker_result() -> TranscriptionResult:
    return TranscriptionResult.model_validate(
        {
            "text": "Hello Hi",
            "language_code": "en",
            "audio_duration_secs": 2.0,
            "words": [
                {"text": "Hello", "start": 0.0, "end": 1.0, "type": "word", "speaker_id": "speaker_0"},
                {"text": "Hi", "start": 1.0, "end": 2.0, "type": "word", "speaker_id": "speaker_1"},
            ],
        }
    )


def test_caption_request_writes_one_document_batch_and_deterministic_sidecars(tmp_path):
    first = export_deliverables(
        _result(),
        tmp_path,
        "clip",
        [Deliverable.SRT, Deliverable.VTT],
        caption_options=CaptionExportOptions(timing_mode=CaptionTimingMode.SOURCE),
    )
    document_text = (tmp_path / "clip.caption-document.json").read_text()
    report_text = (tmp_path / "clip.caption-qc.json").read_text()

    second = export_deliverables(
        _result(),
        tmp_path,
        "clip",
        [Deliverable.SRT, Deliverable.VTT],
        caption_options=CaptionExportOptions(timing_mode=CaptionTimingMode.SOURCE),
    )

    assert first.disposition is CaptionRenderingDisposition.WRITTEN
    assert first.interpretation is not None
    assert set(first.paths) == {"srt", "vtt", "caption_document", "caption_qc"}
    assert document_text == (tmp_path / "clip.caption-document.json").read_text()
    assert report_text == (tmp_path / "clip.caption-qc.json").read_text()
    assert first.interpretation.document.document_hash == second.interpretation.document.document_hash
    assert CaptionDocument.model_validate_json(document_text) == first.interpretation.document
    assert CaptionQCReport.model_validate_json(report_text) == first.report
    assert "00:00:00,000 --> 00:00:01,000" in (tmp_path / "clip.srt").read_text()
    assert "00:00:00.000 --> 00:00:01.000" in (tmp_path / "clip.vtt").read_text()


def test_draft_failure_writes_caption_and_strict_failure_only_writes_diagnostics(tmp_path):
    fast = _result(end=0.5, text="This caption cannot fit in half a second.")
    draft = export_deliverables(
        fast,
        tmp_path / "draft",
        "clip",
        [Deliverable.SRT],
        caption_options=CaptionExportOptions(
            timing_mode=CaptionTimingMode.SOURCE,
            export_policy=CaptionExportPolicy.DRAFT,
        ),
    )
    assert draft.disposition is CaptionRenderingDisposition.DRAFT
    assert set(draft.paths) == {"srt", "caption_document", "caption_qc"}

    strict_dir = tmp_path / "strict"
    strict_dir.mkdir()
    previous = strict_dir / "clip.srt"
    previous.write_text("previous caption")
    strict = export_deliverables(
        fast,
        strict_dir,
        "clip",
        [Deliverable.SRT],
        caption_options=CaptionExportOptions(
            timing_mode=CaptionTimingMode.SOURCE,
            export_policy=CaptionExportPolicy.STRICT,
        ),
    )
    assert strict.disposition is CaptionRenderingDisposition.BLOCKED
    assert set(strict.paths) == {"caption_document", "caption_qc"}
    assert previous.read_text() == "previous caption"


def test_unrenderable_source_blocks_caption_in_both_policies(tmp_path):
    untimed = TranscriptionResult.model_validate(
        {
            "text": "Untimed speech",
            "language_code": "en",
            "words": [{"text": "Untimed speech", "type": "word"}],
        }
    )
    exported = export_deliverables(
        untimed,
        tmp_path,
        "clip",
        [Deliverable.SRT],
        caption_options=CaptionExportOptions(export_policy=CaptionExportPolicy.DRAFT),
    )
    assert exported.disposition is CaptionRenderingDisposition.BLOCKED
    assert set(exported.paths) == {"caption_document", "caption_qc"}
    assert not (tmp_path / "clip.srt").exists()
    rules = {item.rule_id for item in exported.report.findings}
    assert "UNTIMED_SOURCE_CONTENT" in rules
    assert "CAPTION_RENDERING_BLOCKED" in rules


def test_editorial_review_requirement_writes_draft_and_blocks_strict_caption(tmp_path):
    draft = export_deliverables(
        _audio_event_result(),
        tmp_path / "draft",
        "clip",
        [Deliverable.SRT],
        caption_options=CaptionExportOptions(export_policy=CaptionExportPolicy.DRAFT),
    )
    strict = export_deliverables(
        _audio_event_result(),
        tmp_path / "strict",
        "clip",
        [Deliverable.SRT],
        caption_options=CaptionExportOptions(export_policy=CaptionExportPolicy.STRICT),
    )

    assert draft.disposition is CaptionRenderingDisposition.DRAFT
    assert "srt" in draft.paths
    assert draft.report.editorial_coverage.value == "approval_required"
    assert strict.disposition is CaptionRenderingDisposition.BLOCKED
    assert set(strict.paths) == {"caption_document", "caption_qc"}
    assert strict.report.technical_status.value == "warning"


def test_multi_speaker_identity_review_drives_draft_strict_and_status(tmp_path):
    draft = export_deliverables(
        _multi_speaker_result(),
        tmp_path / "draft-speakers",
        "clip",
        [Deliverable.SRT],
        caption_options=CaptionExportOptions(export_policy=CaptionExportPolicy.DRAFT),
    )
    strict = export_deliverables(
        _multi_speaker_result(),
        tmp_path / "strict-speakers",
        "clip",
        [Deliverable.SRT],
        caption_options=CaptionExportOptions(export_policy=CaptionExportPolicy.STRICT),
    )

    assert draft.disposition is CaptionRenderingDisposition.DRAFT
    assert completion_message(draft) == "Caption review required"
    assert strict.disposition is CaptionRenderingDisposition.BLOCKED
    assert completion_message(strict) == "Caption export blocked"
    assert "srt" not in strict.paths


def test_noncaption_export_has_no_caption_work_or_sidecars(tmp_path):
    exported = export_deliverables(_result(), tmp_path, "clip", [Deliverable.JSON])
    assert exported.disposition is CaptionRenderingDisposition.NOT_REQUESTED
    assert exported.interpretation is None
    assert exported.report is None
    assert set(exported.paths) == {"json"}
    assert not list(tmp_path.glob("*.caption-*.json"))


def test_legacy_wrapper_defaults_to_exact_source_timing_and_csv_is_invariant(tmp_path):
    result = _result(end=0.3, text="Hi.")
    source = write_deliverables(
        result,
        tmp_path / "source",
        "clip",
        [Deliverable.SRT, Deliverable.DUB_CSV],
    )
    house = write_deliverables(
        result,
        tmp_path / "house",
        "clip",
        [Deliverable.SRT, Deliverable.DUB_CSV],
        readable_subtitles=True,
    )
    assert "00:00:00,300" in source["srt"].read_text()
    assert "00:00:01,000" in house["srt"].read_text()
    assert source["dub_csv"].read_text() == house["dub_csv"].read_text()


def test_explicit_and_legacy_timing_conflict_fails_clearly(tmp_path):
    with pytest.raises(ValueError, match="select different modes"):
        export_deliverables(
            _result(),
            tmp_path,
            "clip",
            [Deliverable.SRT],
            caption_options=CaptionExportOptions(timing_mode=CaptionTimingMode.HOUSE),
            readable_subtitles=False,
        )


def test_planned_paths_include_implicit_caption_sidecars(tmp_path):
    paths = deliverable_paths(tmp_path, "clip", [Deliverable.SRT, Deliverable.DOCX])
    assert [path.name for path in paths] == [
        "clip.srt",
        "clip.docx",
        "clip.caption-document.json",
        "clip.caption-qc.json",
    ]


def test_partial_atomic_replace_error_reports_committed_paths(tmp_path, monkeypatch):
    real_replace = writer.os.replace
    calls = 0

    def fail_second(source, target):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated replacement failure")
        return real_replace(source, target)

    monkeypatch.setattr(writer.os, "replace", fail_second)
    with pytest.raises(ExportWriteError) as raised:
        export_deliverables(_result(), tmp_path, "clip", [Deliverable.SRT])

    assert set(raised.value.written_paths) == {"caption_document"}
    assert (tmp_path / "clip.caption-document.json").exists()
    assert not (tmp_path / "clip.caption-qc.json").exists()
    assert not list(tmp_path.glob(".*.tmp"))
