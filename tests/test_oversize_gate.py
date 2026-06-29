"""Oversize warn + acknowledge gate (processor + queue level)."""

from __future__ import annotations

import threading

import pytest

from elevenlabs_helper.engine.config import EngineSettings
from elevenlabs_helper.engine.media import inspect as inspect_mod
from elevenlabs_helper.engine.jobs.models import JobStatus
from elevenlabs_helper.engine.jobs.queue import JobQueue
from elevenlabs_helper.engine.jobs.store import JobStore
from elevenlabs_helper.engine.processors.base import ProcessContext
from elevenlabs_helper.engine.processors.speech_to_text import (
    PermanentJobError,
    SpeechToTextProcessor,
)
from elevenlabs_helper.engine.service import make_job


@pytest.fixture
def tiny_limit(monkeypatch):
    # Force every non-empty file to look "oversize". Patch where it's used (the
    # constant is bound into inspect.py at import time).
    monkeypatch.setattr(inspect_mod, "ELEVENLABS_MAX_FILE_BYTES", 1)


def test_unacknowledged_oversize_fails_permanently(tmp_path, dummy_mp3, tiny_limit):
    settings = EngineSettings()
    settings.output_root = tmp_path / "out"
    job = make_job(dummy_mp3, settings)  # acknowledged_oversize defaults False
    ctx = ProcessContext(api_key="k", settings=settings, base_url="http://unused")
    with pytest.raises(PermanentJobError):
        SpeechToTextProcessor().run(job, ctx)


def test_acknowledged_oversize_proceeds(tmp_path, dummy_mp3, mock_elevenlabs, tiny_limit):
    settings = EngineSettings()
    settings.output_root = tmp_path / "out"
    store = JobStore(db_path=tmp_path / "jobs.db")
    done = threading.Event()
    queue = JobQueue(
        store, settings,
        base_url=mock_elevenlabs.base_url,
        on_update=lambda j: done.set() if j.status in (JobStatus.DONE, JobStatus.FAILED) else None,
        api_key_provider=lambda: "key",
    )
    job = make_job(dummy_mp3, settings)
    job.acknowledged_oversize = True
    queue.add(job)
    queue.start()
    assert done.wait(timeout=30)
    queue.stop()
    assert store.get(job.id).status == JobStatus.DONE
    store.close()
