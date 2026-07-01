"""History-JSON persistence + free re-export (no API)."""

from __future__ import annotations

from pathlib import Path

from elevenlabs_helper.engine.config import Deliverable, EngineSettings
from elevenlabs_helper.engine.history import history_path
from elevenlabs_helper.engine.jobs.models import JobStatus
from elevenlabs_helper.engine.jobs.store import JobStore
from elevenlabs_helper.engine.processors.base import ProcessContext
from elevenlabs_helper.engine.processors.speech_to_text import SpeechToTextProcessor
from elevenlabs_helper.engine.service import Engine, ReexportError
from elevenlabs_helper.engine.service import make_job


def _run_one(tmp_path, dummy_mp3, mock_elevenlabs):
    settings = EngineSettings()
    settings.output_root = tmp_path / "out"
    store = JobStore(db_path=tmp_path / "jobs.db")
    job = make_job(dummy_mp3, settings)
    ctx = ProcessContext(api_key="k", settings=settings, base_url=mock_elevenlabs.base_url)
    SpeechToTextProcessor().run(job, ctx)
    store.upsert(job)
    return settings, store, job


def test_history_saved_and_not_beside_outputs(tmp_path, dummy_mp3, mock_elevenlabs):
    _, store, job = _run_one(tmp_path, dummy_mp3, mock_elevenlabs)
    out = Path(job.output_dir)
    assert (out / "sample.srt").exists() and (out / "sample.vtt").exists()
    assert not (out / "sample.json").exists()          # no JSON beside outputs by default
    assert job.history_json and history_path(job.id).exists()  # canonical JSON in app space
    store.close()


def test_reexport_regenerates_after_deletion(tmp_path, dummy_mp3, mock_elevenlabs):
    settings, store, job = _run_one(tmp_path, dummy_mp3, mock_elevenlabs)
    srt = Path(job.output_dir) / "sample.srt"
    srt.unlink()                                        # user "loses" the SRT
    assert not srt.exists()

    engine = Engine(settings=settings, store=store, base_url=mock_elevenlabs.base_url)
    arts = engine.reexport(job.id)                      # no API call
    assert srt.exists()                                 # regenerated for free
    assert mock_elevenlabs.calls == 1                   # only the original transcription

    # Format override adds a user-facing JSON copy.
    arts2 = engine.reexport(job.id, deliverables=[Deliverable.SRT, Deliverable.JSON])
    assert (Path(job.output_dir) / "sample.json").exists()
    assert "json" in arts2
    store.close()


def test_archive_hides_from_active_but_keeps_history_and_reexport(tmp_path, dummy_mp3, mock_elevenlabs):
    settings, store, job = _run_one(tmp_path, dummy_mp3, mock_elevenlabs)
    engine = Engine(settings=settings, store=store, base_url=mock_elevenlabs.base_url)

    engine.archive(job.id)
    assert all(j.id != job.id for j in engine.jobs())        # gone from the active list
    assert any(j.id == job.id for j in engine.all_jobs())    # still recoverable in history
    assert history_path(job.id).exists()                     # recovery JSON preserved

    (Path(job.output_dir) / "sample.srt").unlink()
    engine.reexport(job.id)                                   # re-export still works
    assert (Path(job.output_dir) / "sample.srt").exists()
    store.close()


def test_delete_permanently_removes_record_and_history(tmp_path, dummy_mp3, mock_elevenlabs):
    settings, store, job = _run_one(tmp_path, dummy_mp3, mock_elevenlabs)
    engine = Engine(settings=settings, store=store, base_url=mock_elevenlabs.base_url)
    assert history_path(job.id).exists()

    engine.delete_permanently(job.id)
    assert store.get(job.id) is None
    assert not history_path(job.id).exists()
    store.close()


def test_reexport_without_history_errors(tmp_path, dummy_mp3, mock_elevenlabs):
    settings = EngineSettings()
    settings.output_root = tmp_path / "out"
    settings.keep_history_json = False                  # retention off -> nothing to re-export from
    store = JobStore(db_path=tmp_path / "jobs.db")
    job = make_job(dummy_mp3, settings)
    ctx = ProcessContext(api_key="k", settings=settings, base_url=mock_elevenlabs.base_url)
    SpeechToTextProcessor().run(job, ctx)
    store.upsert(job)
    assert job.history_json is None

    engine = Engine(settings=settings, store=store, base_url=mock_elevenlabs.base_url)
    import pytest
    with pytest.raises(ReexportError):
        engine.reexport(job.id)
    store.close()
