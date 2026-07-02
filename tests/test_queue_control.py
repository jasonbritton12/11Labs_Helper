"""Cancel and resume-after-restart coverage."""

from __future__ import annotations

import threading

from elevenlabs_helper.engine.config import EngineSettings
from elevenlabs_helper.engine.jobs.models import Job, JobStatus
from elevenlabs_helper.engine.jobs.queue import JobQueue
from elevenlabs_helper.engine.jobs.store import JobStore
from elevenlabs_helper.engine.service import make_job


def test_cancel_queued_job_is_not_processed(tmp_path, mock_elevenlabs):
    settings = EngineSettings()
    settings.output_root = tmp_path / "out"
    store = JobStore(db_path=tmp_path / "jobs.db")
    queue = JobQueue(
        store, settings,
        base_url=mock_elevenlabs.base_url,
        api_key_provider=lambda: "key",
    )
    # A nonexistent source would fail if processed; cancel before the worker starts.
    job = Job(
        source_path=str(tmp_path / "missing.mp3"),
        output_dir=str(tmp_path / "out" / "missing"),
    )
    queue.add(job)
    queue.cancel(job.id)
    queue.start()
    threading.Event().wait(0.5)  # give the worker a moment; nothing should run
    queue.stop()
    assert store.get(job.id).status == JobStatus.CANCELED
    assert mock_elevenlabs.calls == 0
    store.close()


def test_resume_unfinished_restages_without_running(tmp_path, dummy_mp3, mock_elevenlabs):
    # A job interrupted mid-flight must return to STAGED (never auto-run on launch).
    settings = EngineSettings()
    settings.output_root = tmp_path / "out"
    db = tmp_path / "jobs.db"

    seed_store = JobStore(db_path=db)
    job = make_job(dummy_mp3, settings)
    job.status = JobStatus.UPLOADING
    seed_store.upsert(job)
    seed_store.close()

    store = JobStore(db_path=db)
    queue = JobQueue(
        store, settings, base_url=mock_elevenlabs.base_url, api_key_provider=lambda: "key"
    )
    queue.start()
    queue.resume_unfinished()
    threading.Event().wait(0.5)  # give the worker a moment; it must NOT run the job
    queue.stop()
    assert store.get(job.id).status == JobStatus.STAGED
    assert mock_elevenlabs.calls == 0
    store.close()


def test_stage_then_run_processes(tmp_path, dummy_mp3, mock_elevenlabs):
    settings = EngineSettings()
    settings.output_root = tmp_path / "out"
    store = JobStore(db_path=tmp_path / "jobs.db")
    done = threading.Event()
    queue = JobQueue(
        store, settings, base_url=mock_elevenlabs.base_url,
        on_update=lambda j: done.set() if j.status == JobStatus.DONE else None,
        api_key_provider=lambda: "key",
    )
    job = make_job(dummy_mp3, settings)
    queue.stage(job)
    queue.start()
    threading.Event().wait(0.4)  # staged: nothing runs yet
    assert store.get(job.id).status == JobStatus.STAGED
    assert mock_elevenlabs.calls == 0

    assert queue.run_staged() == 1   # explicit Run
    assert done.wait(timeout=30)
    queue.stop()
    assert store.get(job.id).status == JobStatus.DONE
    store.close()
