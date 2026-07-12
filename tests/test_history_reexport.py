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


def test_rerun_with_existing_history_skips_upload(tmp_path, dummy_mp3, mock_elevenlabs):
    # SER-025: re-running a job that already has a transcript (e.g. interrupted after
    # transcription, re-staged) must re-export from history — never re-upload/re-bill.
    settings, store, job = _run_one(tmp_path, dummy_mp3, mock_elevenlabs)
    assert mock_elevenlabs.calls == 1
    (Path(job.output_dir) / "sample.srt").unlink()

    ctx = ProcessContext(api_key="k", settings=settings, base_url=mock_elevenlabs.base_url)
    SpeechToTextProcessor().run(job, ctx)   # history_json present -> fast path
    assert (Path(job.output_dir) / "sample.srt").exists()
    assert mock_elevenlabs.calls == 1       # no second transcription
    assert job.status == JobStatus.DONE
    store.close()


def test_reexport_empty_formats_falls_back_to_job_defaults(tmp_path, dummy_mp3, mock_elevenlabs):
    settings, store, job = _run_one(tmp_path, dummy_mp3, mock_elevenlabs)  # SRT+VTT
    (Path(job.output_dir) / "sample.srt").unlink()
    engine = Engine(settings=settings, store=store, base_url=mock_elevenlabs.base_url)
    arts = engine.reexport(job.id, deliverables=[])   # empty -> use the job's formats
    assert set(arts) == {"srt", "vtt"}
    store.close()


def test_reexport_to_alternate_directory(tmp_path, dummy_mp3, mock_elevenlabs):
    settings, store, job = _run_one(tmp_path, dummy_mp3, mock_elevenlabs)
    engine = Engine(settings=settings, store=store, base_url=mock_elevenlabs.base_url)
    alt = tmp_path / "elsewhere"
    engine.reexport(job.id, out_dir=alt)
    assert (alt / "sample.srt").exists()
    store.close()


def test_requeue_unarchives_and_queues(tmp_path, dummy_mp3, mock_elevenlabs):
    settings = EngineSettings()
    settings.output_root = tmp_path / "out"
    store = JobStore(db_path=tmp_path / "jobs.db")
    job = make_job(dummy_mp3, settings)
    job.status = JobStatus.FAILED
    job.archived = True
    store.upsert(job)

    engine = Engine(settings=settings, store=store, base_url=mock_elevenlabs.base_url)
    engine.requeue(job.id)   # worker not started; just checks state transition
    saved = store.get(job.id)
    assert saved.archived is False
    assert saved.status == JobStatus.QUEUED
    store.close()


def test_prune_history_removes_old_files_only(tmp_path):
    import os
    import time as _time

    from elevenlabs_helper.engine.history import history_dir, prune_history

    old = history_dir() / "old.json"
    old.write_text("{}")
    stamp = _time.time() - 40 * 86400
    os.utime(old, (stamp, stamp))
    new = history_dir() / "new.json"
    new.write_text("{}")

    assert prune_history(30) == 1          # only the 40-day-old file
    assert not old.exists() and new.exists()
    assert prune_history(0) == 0 and new.exists()   # 0 == keep forever


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
