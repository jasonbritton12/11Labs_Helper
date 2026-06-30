"""Shared fixtures: a generated sample media file and a mock ElevenLabs server."""

from __future__ import annotations

import json
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

CANNED_RESULT = {
    "language_code": "eng",
    "language_probability": 0.99,
    "audio_duration_secs": 3.6,
    "text": "Hello world. How are you?",
    "words": [
        {"text": "Hello", "start": 0.0, "end": 0.5, "type": "word", "speaker_id": "speaker_0"},
        {"text": "world.", "start": 0.6, "end": 1.0, "type": "word", "speaker_id": "speaker_0"},
        {"text": "How", "start": 2.5, "end": 2.8, "type": "word", "speaker_id": "speaker_1"},
        {"text": "are", "start": 2.9, "end": 3.1, "type": "word", "speaker_id": "speaker_1"},
        {"text": "you?", "start": 3.2, "end": 3.6, "type": "word", "speaker_id": "speaker_1"},
    ],
}


def _have_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None


requires_ffmpeg = pytest.mark.skipif(not _have_ffmpeg(), reason="ffmpeg not installed")


@pytest.fixture
def dummy_mp3(tmp_path) -> str:
    """A .mp3 file with arbitrary bytes — fine for upload-path tests (mock doesn't decode).

    The app no longer uses ffmpeg, so tests don't need a real audio file to exercise
    the upload/transcribe/export pipeline.
    """
    path = tmp_path / "sample.mp3"
    path.write_bytes(b"ID3\x03\x00" + b"\x00" * 1024)
    return str(path)


@pytest.fixture(scope="session")
def real_mp3(tmp_path_factory) -> str:
    """A genuine short .mp3 (built with ffmpeg if available) for duration-reading tests."""
    if not _have_ffmpeg():
        pytest.skip("ffmpeg not installed (used only to synthesize a real mp3 fixture)")
    path = tmp_path_factory.mktemp("media") / "tone.mp3"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
         "-c:a", "libmp3lame", str(path)],
        check=True,
    )
    return str(path)


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # silence
        pass

    def do_GET(self):  # noqa: N802 - used by validate_key (/v1/user)
        server = self.server
        if not self.headers.get("xi-api-key"):
            self._send(401, {"detail": "missing key"})
            return
        self._send(getattr(server, "get_status", 200), getattr(server, "get_body", {"user_id": "test-user"}))

    def do_POST(self):  # noqa: N802
        server = self.server
        length = int(self.headers.get("Content-Length", 0))
        self.rfile.read(length)  # drain the multipart upload
        server.calls += 1

        if not self.headers.get("xi-api-key"):
            self._send(401, {"detail": "missing key"})
            return
        if server.fail_times > 0:
            server.fail_times -= 1
            self._send(server.fail_status, {"detail": "transient"})
            return
        self._send(200, server.result)

    def _send(self, code: int, body: dict) -> None:
        payload = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


@pytest.fixture
def mock_elevenlabs():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    server.calls = 0
    server.fail_times = 0
    server.fail_status = 429
    server.result = CANNED_RESULT
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    server.base_url = f"http://{host}:{port}"
    try:
        yield server
    finally:
        server.shutdown()
        thread.join(timeout=2)
