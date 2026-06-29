import pytest

from elevenlabs_helper.engine.config import TranscriptionParams
from elevenlabs_helper.engine.elevenlabs.client import (
    ElevenLabsApiError,
    ElevenLabsAuthError,
    transcribe_file,
)


@pytest.fixture
def audio_file(tmp_path):
    p = tmp_path / "a.flac"
    p.write_bytes(b"not really audio")
    return p


def test_success(mock_elevenlabs, audio_file):
    result = transcribe_file(
        audio_file, TranscriptionParams(), "key", base_url=mock_elevenlabs.base_url
    )
    assert result.text == "Hello world. How are you?"
    assert mock_elevenlabs.calls == 1


def test_retries_then_succeeds(mock_elevenlabs, audio_file):
    mock_elevenlabs.fail_times = 2
    mock_elevenlabs.fail_status = 429
    seen = []
    result = transcribe_file(
        audio_file,
        TranscriptionParams(),
        "key",
        base_url=mock_elevenlabs.base_url,
        base_delay=0.01,
        on_retry=lambda *a: seen.append(a),
    )
    assert result.text.startswith("Hello")
    assert mock_elevenlabs.calls == 3
    assert len(seen) == 2


def test_auth_error_not_retried(mock_elevenlabs, audio_file):
    with pytest.raises(ElevenLabsAuthError):
        transcribe_file(audio_file, TranscriptionParams(), "", base_url=mock_elevenlabs.base_url)
    assert mock_elevenlabs.calls == 1


def test_exhausted_retries_raises_api_error(mock_elevenlabs, audio_file):
    mock_elevenlabs.fail_times = 99
    mock_elevenlabs.fail_status = 503
    with pytest.raises(ElevenLabsApiError):
        transcribe_file(
            audio_file,
            TranscriptionParams(),
            "key",
            base_url=mock_elevenlabs.base_url,
            max_retries=2,
            base_delay=0.01,
        )
