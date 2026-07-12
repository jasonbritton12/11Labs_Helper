"""Stage 1 remediation coverage (E1, E4/U2, SSR-001, U3 pause, SSR-003 raw-json)."""

from __future__ import annotations

import threading

import pytest

from elevenlabs_helper.engine.config import Deliverable, EngineSettings, TranscriptionParams
from elevenlabs_helper.engine.elevenlabs import client as client_mod
from elevenlabs_helper.engine.elevenlabs.client import (
    ElevenLabsApiError,
    transcribe_file,
    validate_key,
)
from elevenlabs_helper.engine.exporters.writer import write_deliverables
from elevenlabs_helper.engine.jobs.models import JobStatus
from elevenlabs_helper.engine.jobs.queue import JobQueue
from elevenlabs_helper.engine.jobs.store import JobStore
from elevenlabs_helper.engine.processors.base import ProcessContext
from elevenlabs_helper.engine.processors.speech_to_text import SpeechToTextProcessor
from elevenlabs_helper.engine.service import make_job

from .conftest import CANNED_RESULT


def _settings(tmp_path):
    s = EngineSettings()
    s.output_root = tmp_path / "out"
    s.max_retries = 1
    s.retry_base_delay_secs = 0.01
    return s


# --- E1: export failure is permanent (no re-upload/re-bill) ------------------
def test_export_failure_is_permanent_no_reupload(tmp_path, dummy_mp3, mock_elevenlabs, monkeypatch):
    import elevenlabs_helper.engine.processors.speech_to_text as stt

    def boom(*a, **k):
        raise ValueError("synthetic exporter bug")

    monkeypatch.setattr(stt, "write_deliverables", boom)

    settings = _settings(tmp_path)
    store = JobStore(db_path=tmp_path / "jobs.db")
    done = threading.Event()
    queue = JobQueue(
        store, settings, base_url=mock_elevenlabs.base_url,
        on_update=lambda j: done.set() if j.status in (JobStatus.DONE, JobStatus.FAILED) else None,
        api_key_provider=lambda: "k",
    )
    job = make_job(dummy_mp3, settings)
    queue.add(job); queue.start()
    assert done.wait(timeout=30)
    queue.stop()
    assert store.get(job.id).status == JobStatus.FAILED
    assert mock_elevenlabs.calls == 1  # uploaded once; the export bug did NOT retry
    store.close()


# --- E4/U2: empty transcript surfaces as "No speech detected" ----------------
def test_empty_transcript_message(tmp_path, dummy_mp3, mock_elevenlabs):
    mock_elevenlabs.result = {"text": "", "words": []}
    settings = _settings(tmp_path)
    job = make_job(dummy_mp3, settings)
    ctx = ProcessContext(api_key="k", settings=settings, base_url=mock_elevenlabs.base_url)
    SpeechToTextProcessor().run(job, ctx)
    assert job.status == JobStatus.DONE
    assert job.message == "No speech detected"


# --- SSR-001: HTTPS enforced for credentialed calls --------------------------
def test_https_required_for_transcribe(tmp_path, dummy_mp3):
    with pytest.raises(ElevenLabsApiError):
        transcribe_file(dummy_mp3, TranscriptionParams(), "k", base_url="http://evil.example")


def test_https_required_for_validate_key():
    # validate_key stays total: returns ("invalid", msg) rather than raising.
    status, msg = validate_key("k", base_url="http://evil.example")
    assert status == "invalid"
    assert "insecure" in msg.lower()


def test_loopback_allowed_for_tests():
    # Should not raise (host is loopback); connection itself will fail -> unverified.
    status, _ = validate_key("k", base_url="http://127.0.0.1:1", timeout=0.3)
    assert status == "unverified"


# --- Deliverables are opt-in; no JSON in the output folder unless selected ---
def test_writer_no_json_unless_selected(tmp_path):
    from elevenlabs_helper.engine.elevenlabs.models import TranscriptionResult

    result = TranscriptionResult.model_validate(CANNED_RESULT)
    arts = write_deliverables(result, tmp_path, "clip", [Deliverable.SRT])
    assert "json" not in arts
    assert not (tmp_path / "clip.json").exists()
    assert (tmp_path / "clip.srt").exists()
