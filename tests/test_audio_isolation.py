"""Voice Isolation client, processor, routing, and limit coverage."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from elevenlabs_helper.engine.config import EngineSettings
from elevenlabs_helper.engine.elevenlabs.audio_isolation import (
    _audio_extension,
    isolate_dialog_file,
)
from elevenlabs_helper.engine.elevenlabs.client import (
    ElevenLabsApiError,
    ElevenLabsAuthError,
)
from elevenlabs_helper.engine.jobs.models import Job, JobStatus, JobType
from elevenlabs_helper.engine.jobs.queue import JobQueue
from elevenlabs_helper.engine.jobs.store import JobStore
from elevenlabs_helper.engine.media.inspect import (
    MediaInfo,
    voice_isolation_limit_warnings,
)
from elevenlabs_helper.engine.processors.base import ProcessContext
from elevenlabs_helper.engine.processors.voice_isolation import VoiceIsolationProcessor
from elevenlabs_helper.engine.service import make_job
from elevenlabs_helper.engine.cli import build_parser


def _settings(tmp_path: Path) -> EngineSettings:
    settings = EngineSettings()
    settings.output_root = tmp_path / "out"
    settings.max_retries = 2
    settings.retry_base_delay_secs = 0.01
    return settings


@pytest.mark.parametrize(
    "content_type,header,expected",
    [
        ("audio/mpeg", b"ignored", ".mp3"),
        ("application/octet-stream", b"RIFF\x00\x00\x00\x00WAVE", ".wav"),
        ("application/octet-stream", b"fLaC", ".flac"),
        ("application/octet-stream", b"OggS", ".ogg"),
        ("application/octet-stream", b"\x00\x00\x00\x18ftyp", ".m4a"),
        ("application/octet-stream", b"unknown", ".mp3"),
    ],
)
def test_audio_extension(content_type, header, expected):
    assert _audio_extension(content_type, header) == expected


def test_client_streams_native_audio_and_uses_audio_field(
    tmp_path, dummy_wav, mock_elevenlabs
):
    output = isolate_dialog_file(
        dummy_wav,
        tmp_path,
        "key",
        base_url=mock_elevenlabs.base_url,
    )
    assert output.name == "sample_DX.mp3"
    assert output.read_bytes() == mock_elevenlabs.isolation_result
    assert mock_elevenlabs.post_paths == ["/v1/audio-isolation"]
    assert b'name="audio"' in mock_elevenlabs.last_body
    assert b'name="file"' not in mock_elevenlabs.last_body


def test_client_retries_then_succeeds(tmp_path, dummy_mp3, mock_elevenlabs):
    mock_elevenlabs.fail_times = 1
    seen = []
    output = isolate_dialog_file(
        dummy_mp3,
        tmp_path,
        "key",
        base_url=mock_elevenlabs.base_url,
        base_delay=0.01,
        on_retry=lambda *args: seen.append(args),
    )
    assert output.exists()
    assert mock_elevenlabs.calls == 2
    assert len(seen) == 1


def test_client_auth_error_is_not_retried(tmp_path, dummy_mp3, mock_elevenlabs):
    with pytest.raises(ElevenLabsAuthError):
        isolate_dialog_file(
            dummy_mp3,
            tmp_path,
            "",
            base_url=mock_elevenlabs.base_url,
        )
    assert mock_elevenlabs.calls == 1


def test_client_rejects_empty_success_and_removes_partial(
    tmp_path, dummy_mp3, mock_elevenlabs
):
    mock_elevenlabs.isolation_result = b""
    with pytest.raises(ElevenLabsApiError, match="empty"):
        isolate_dialog_file(
            dummy_mp3,
            tmp_path,
            "key",
            base_url=mock_elevenlabs.base_url,
        )
    assert list(tmp_path.glob("*.part")) == []
    assert list(tmp_path.glob("*_DX.*")) == []


def test_client_rejects_json_success(tmp_path, dummy_mp3, mock_elevenlabs):
    mock_elevenlabs.isolation_result = b'{"detail":"not audio"}'
    mock_elevenlabs.isolation_content_type = "application/json"
    with pytest.raises(ElevenLabsApiError, match="JSON instead of isolated audio"):
        isolate_dialog_file(
            dummy_mp3,
            tmp_path,
            "key",
            base_url=mock_elevenlabs.base_url,
        )
    assert list(tmp_path.glob("*_DX.*")) == []


def test_client_honors_preflight_cancel(
    tmp_path, dummy_mp3, mock_elevenlabs
):
    canceled = threading.Event()
    canceled.set()
    from elevenlabs_helper.engine.elevenlabs.client import TransferCanceled

    with pytest.raises(TransferCanceled):
        isolate_dialog_file(
            dummy_mp3,
            tmp_path,
            "key",
            base_url=mock_elevenlabs.base_url,
            cancel_event=canceled,
        )
    assert mock_elevenlabs.calls == 0


def test_client_rejects_insecure_remote_url(tmp_path, dummy_mp3):
    with pytest.raises(ElevenLabsApiError):
        isolate_dialog_file(
            dummy_mp3,
            tmp_path,
            "key",
            base_url="http://evil.example",
        )


def test_processor_saves_dialog_artifact(tmp_path, dummy_mp4, mock_elevenlabs):
    settings = _settings(tmp_path)
    job = make_job(dummy_mp4, settings, job_type=JobType.VOICE_ISOLATION)
    ctx = ProcessContext(api_key="key", settings=settings, base_url=mock_elevenlabs.base_url)

    VoiceIsolationProcessor().run(job, ctx)

    assert job.status == JobStatus.DONE
    assert job.message == "Dialog isolated"
    assert job.deliverables == []
    assert Path(job.artifacts["dialog"]).read_bytes() == mock_elevenlabs.isolation_result


def test_queue_routes_voice_isolation_only_after_run(
    tmp_path, dummy_wav, mock_elevenlabs
):
    settings = _settings(tmp_path)
    store = JobStore(db_path=tmp_path / "jobs.db")
    done = threading.Event()
    queue = JobQueue(
        store,
        settings,
        base_url=mock_elevenlabs.base_url,
        api_key_provider=lambda: "key",
        on_update=lambda job: done.set() if job.status == JobStatus.DONE else None,
    )
    job = make_job(dummy_wav, settings, job_type=JobType.VOICE_ISOLATION)
    queue.stage(job)
    queue.start()
    assert mock_elevenlabs.calls == 0

    assert queue.run_staged() == 1
    assert done.wait(timeout=10)
    queue.stop()

    saved = store.get(job.id)
    assert saved is not None
    assert saved.job_type == JobType.VOICE_ISOLATION
    assert Path(saved.artifacts["dialog"]).exists()
    assert mock_elevenlabs.post_paths == ["/v1/audio-isolation"]
    store.close()


def test_old_job_json_defaults_to_transcription():
    raw = Job(source_path="source.mp3", output_dir="out").model_dump()
    raw.pop("job_type")
    assert Job.model_validate(raw).job_type == JobType.TRANSCRIPTION


def test_voice_isolation_limits_are_separate():
    warnings = voice_isolation_limit_warnings(
        MediaInfo(size_bytes=501 * 1024**2, duration_secs=3601)
    )
    assert len(warnings) == 2
    assert any("500" in warning for warning in warnings)
    assert any("1h" in warning for warning in warnings)


def test_cli_exposes_explicit_isolate_command():
    args = build_parser().parse_args(["isolate", "clip.wav", "--out", "out"])
    assert args.inputs == ["clip.wav"]
    assert args.out == "out"
