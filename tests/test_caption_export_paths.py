"""P07 caption option snapshots and persisted export-batch integration."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from elevenlabs_helper.engine.captions import (
    CaptionExportOptions,
    CaptionExportPolicy,
    CaptionRenderingDisposition,
    CaptionTimingMode,
    ExportResult,
)
from elevenlabs_helper.engine.config import Deliverable, EngineSettings, resolve_caption_options
from elevenlabs_helper.engine.elevenlabs.models import TranscriptionResult
from elevenlabs_helper.engine.jobs.store import JobStore
from elevenlabs_helper.engine.processors.base import ProcessContext
from elevenlabs_helper.engine.processors.speech_to_text import SpeechToTextProcessor
from elevenlabs_helper.engine.service import Engine, make_job


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


def _stored_job(
    tmp_path: Path,
    *,
    result: TranscriptionResult | None = None,
    settings: EngineSettings | None = None,
):
    source = tmp_path / "clip.mp3"
    source.write_bytes(b"ID3\x03\x00" + b"\x00" * 64)
    settings = settings or EngineSettings(output_root=tmp_path / "out")
    store = JobStore(db_path=tmp_path / "jobs.db")
    job = make_job(source, settings)
    history = tmp_path / "history.json"
    history.write_text((result or _result()).model_dump_json(indent=2))
    job.history_json = str(history)
    store.upsert(job)
    return settings, store, job


@pytest.mark.parametrize("from_history", [False, True], ids=["normal", "history-fast-path"])
def test_processor_uses_staged_snapshot_after_settings_change_without_rebilling(
    tmp_path, dummy_mp3, monkeypatch, from_history
):
    """Both processor paths must use the immutable staging-time options."""

    import elevenlabs_helper.engine.processors.speech_to_text as stt

    settings = EngineSettings(
        output_root=tmp_path / "out",
        caption_timing_mode=CaptionTimingMode.SOURCE,
        keep_history_json=False,
    )
    job = make_job(dummy_mp3, settings)
    assert job.staged_caption_options is not None
    assert job.staged_caption_options.timing_mode is CaptionTimingMode.SOURCE

    calls = 0

    def transcribe(*args, **kwargs):
        nonlocal calls
        calls += 1
        return _result()

    monkeypatch.setattr(stt, "transcribe_file", transcribe)
    if from_history:
        history = tmp_path / "saved-history.json"
        history.write_text(_result().model_dump_json(indent=2))
        job.history_json = str(history)

    # A user changing Settings after staging must not change this job's output.
    settings.caption_timing_mode = CaptionTimingMode.HOUSE
    ctx = ProcessContext(api_key="not-used", settings=settings)
    SpeechToTextProcessor().run(job, ctx)

    assert calls == (0 if from_history else 1)
    assert job.latest_caption_options is not None
    assert job.latest_caption_options.timing_mode is CaptionTimingMode.SOURCE
    assert job.latest_caption_batch is not None
    assert job.latest_caption_batch["paths"]["caption_document"].endswith(
        "sample.caption-document.json"
    )


def test_strict_retry_retires_old_caption_artifacts_and_records_retained_files(tmp_path):
    fast = _result(end=0.5, text="This caption cannot fit in half a second.")
    settings, store, job = _stored_job(tmp_path, result=fast)
    engine = Engine(settings=settings, store=store)
    try:
        written = engine.reexport(
            job.id,
            deliverables=[Deliverable.SRT, Deliverable.VTT],
            caption_options=CaptionExportOptions(
                timing_mode=CaptionTimingMode.SOURCE,
                export_policy=CaptionExportPolicy.DRAFT,
            ),
        )
        old_srt = written["srt"]
        old_vtt = written["vtt"]
        old_srt_text = old_srt.read_text()
        old_vtt_text = old_vtt.read_text()

        blocked = engine.reexport(
            job.id,
            deliverables=[Deliverable.SRT, Deliverable.VTT],
            caption_options=CaptionExportOptions(
                timing_mode=CaptionTimingMode.SOURCE,
                export_policy=CaptionExportPolicy.STRICT,
            ),
        )
        saved = store.get(job.id)
        assert saved is not None
        assert set(blocked) == {"caption_document", "caption_qc"}
        assert not ({"srt", "vtt"} & saved.artifacts.keys())
        assert saved.latest_caption_batch is not None
        assert saved.latest_caption_batch["disposition"] == "blocked"
        assert saved.latest_caption_batch["written_formats"] == []
        assert saved.latest_caption_batch["retained_paths"] == {
            "srt": str(old_srt),
            "vtt": str(old_vtt),
        }
        # Strict output leaves the prior files on disk, but does not present them
        # as members of the new document-bound batch.
        assert old_srt.read_text() == old_srt_text
        assert old_vtt.read_text() == old_vtt_text
    finally:
        store.close()


def test_noncaption_reexport_preserves_the_latest_caption_batch(tmp_path):
    settings, store, job = _stored_job(tmp_path)
    engine = Engine(settings=settings, store=store)
    try:
        engine.reexport(job.id, deliverables=[Deliverable.SRT, Deliverable.VTT])
        before = store.get(job.id)
        assert before is not None
        batch = deepcopy(before.latest_caption_batch)
        summary = deepcopy(before.caption_qc_summary)
        options = before.latest_caption_options
        caption_artifacts = {
            key: before.artifacts[key]
            for key in ("srt", "vtt", "caption_document", "caption_qc")
        }

        written = engine.reexport(job.id, deliverables=[Deliverable.JSON])
        after = store.get(job.id)
        assert after is not None
        assert set(written) == {"json"}
        assert after.latest_caption_batch == batch
        assert after.caption_qc_summary == summary
        assert after.latest_caption_options == options
        assert {key: after.artifacts[key] for key in caption_artifacts} == caption_artifacts
    finally:
        store.close()


@pytest.mark.parametrize(
    ("latest", "staged", "explicit", "expected"),
    [
        (
            CaptionExportOptions(
                timing_mode=CaptionTimingMode.HOUSE,
                export_policy=CaptionExportPolicy.STRICT,
            ),
            CaptionExportOptions(timing_mode=CaptionTimingMode.SOURCE),
            CaptionExportOptions(
                timing_mode=CaptionTimingMode.SOURCE,
                export_policy=CaptionExportPolicy.STRICT,
            ),
            CaptionExportOptions(
                timing_mode=CaptionTimingMode.SOURCE,
                export_policy=CaptionExportPolicy.STRICT,
            ),
        ),
        (
            CaptionExportOptions(
                timing_mode=CaptionTimingMode.SOURCE,
                export_policy=CaptionExportPolicy.STRICT,
            ),
            CaptionExportOptions(timing_mode=CaptionTimingMode.HOUSE),
            None,
            CaptionExportOptions(
                timing_mode=CaptionTimingMode.SOURCE,
                export_policy=CaptionExportPolicy.STRICT,
            ),
        ),
        (
            None,
            CaptionExportOptions(timing_mode=CaptionTimingMode.SOURCE),
            None,
            CaptionExportOptions(timing_mode=CaptionTimingMode.SOURCE),
        ),
        (None, None, None, None),
    ],
    ids=["explicit", "latest", "staged", "settings"],
)
def test_reexport_caption_option_precedence(
    tmp_path, monkeypatch, latest, staged, explicit, expected
):
    import elevenlabs_helper.engine.service as service

    settings = EngineSettings(
        output_root=tmp_path / "out",
        caption_timing_mode=CaptionTimingMode.HOUSE,
    )
    settings, store, job = _stored_job(tmp_path, settings=settings)
    job.latest_caption_options = latest
    job.staged_caption_options = staged
    store.upsert(job)
    observed = []

    def capture_export(*args, caption_options, **kwargs):
        observed.append(caption_options)
        return ExportResult(
            paths={},
            options=caption_options,
            disposition=CaptionRenderingDisposition.NOT_REQUESTED,
        )

    monkeypatch.setattr(service, "export_deliverables", capture_export)
    engine = Engine(settings=settings, store=store)
    try:
        engine.reexport(
            job.id,
            deliverables=[Deliverable.JSON],
            caption_options=explicit,
        )
        assert observed == [expected or resolve_caption_options(settings)]
    finally:
        store.close()
