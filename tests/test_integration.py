"""End-to-end: upload -> mock transcribe -> export, via the real queue (no ffmpeg)."""

from __future__ import annotations

import threading
from pathlib import Path

from elevenlabs_helper.engine.config import EngineSettings
from elevenlabs_helper.engine.jobs.models import JobStatus
from elevenlabs_helper.engine.jobs.queue import JobQueue
from elevenlabs_helper.engine.jobs.store import JobStore
from elevenlabs_helper.engine.service import make_job


def _settings(tmp_path: Path) -> EngineSettings:
    s = EngineSettings()
    s.output_root = tmp_path / "out"
    s.max_retries = 1
    s.retry_base_delay_secs = 0.01
    return s


def _run_to_terminal(queue: JobQueue, job, done_evt):
    queue.add(job)
    queue.start()
    assert done_evt.wait(timeout=60), "job did not finish in time"


def test_full_pipeline_and_persistence(tmp_path, dummy_mp3, mock_elevenlabs):
    settings = _settings(tmp_path)
    db = tmp_path / "jobs.db"
    store = JobStore(db_path=db)

    done = threading.Event()

    def on_update(j):
        if j.status in (JobStatus.DONE, JobStatus.FAILED, JobStatus.CANCELED):
            done.set()

    queue = JobQueue(
        store, settings,
        base_url=mock_elevenlabs.base_url,
        on_update=on_update,
        api_key_provider=lambda: "test-key",
    )
    job = make_job(dummy_mp3, settings)
    _run_to_terminal(queue, job, done)
    queue.stop()

    saved = store.get(job.id)
    assert saved.status == JobStatus.DONE, saved.error
    out_dir = Path(saved.output_dir)
    assert (out_dir / "sample.srt").exists()
    assert (out_dir / "sample.vtt").exists()
    assert (out_dir / "sample.docx").exists()
    assert (out_dir / "sample.raw.json").exists()

    # Persistence across "restart": reopen the DB.
    store.close()
    store2 = JobStore(db_path=db)
    reloaded = store2.get(job.id)
    assert reloaded is not None and reloaded.status == JobStatus.DONE
    store2.close()


def test_transient_then_success(tmp_path, dummy_mp3, mock_elevenlabs):
    mock_elevenlabs.fail_times = 2
    mock_elevenlabs.fail_status = 503
    settings = _settings(tmp_path)
    settings.max_retries = 5
    store = JobStore(db_path=tmp_path / "jobs.db")
    done = threading.Event()
    queue = JobQueue(
        store, settings,
        base_url=mock_elevenlabs.base_url,
        on_update=lambda j: done.set() if j.status in (JobStatus.DONE, JobStatus.FAILED) else None,
        api_key_provider=lambda: "test-key",
    )
    job = make_job(dummy_mp3, settings)
    _run_to_terminal(queue, job, done)
    queue.stop()
    assert store.get(job.id).status == JobStatus.DONE
    assert mock_elevenlabs.calls == 3
    store.close()


def test_missing_key_fails_job(tmp_path, dummy_mp3, mock_elevenlabs):
    from elevenlabs_helper.engine.auth import MissingApiKeyError

    settings = _settings(tmp_path)
    store = JobStore(db_path=tmp_path / "jobs.db")
    done = threading.Event()

    def provider():
        raise MissingApiKeyError("no key")

    queue = JobQueue(
        store, settings,
        base_url=mock_elevenlabs.base_url,
        on_update=lambda j: done.set() if j.status == JobStatus.FAILED else None,
        api_key_provider=provider,
    )
    job = make_job(dummy_mp3, settings)
    queue.add(job)
    queue.start()
    assert done.wait(timeout=10)
    queue.stop()
    assert store.get(job.id).status == JobStatus.FAILED
    store.close()
