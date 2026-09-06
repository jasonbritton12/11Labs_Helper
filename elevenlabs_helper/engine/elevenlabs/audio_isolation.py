"""Streaming client for the ElevenLabs Voice Isolation endpoint."""

from __future__ import annotations

import json
import mimetypes
import os
import tempfile
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx

from .client import (
    DEFAULT_BASE_URL,
    DEFAULT_TIMEOUT,
    RETRIABLE_STATUS,
    ElevenLabsApiError,
    ElevenLabsAuthError,
    RetryCallback,
    TransferCanceled,
    _backoff,
    _emit,
    _require_secure,
    _retry_after,
)

VOICE_ISOLATION_PATH = "/v1/audio-isolation"

_CONTENT_TYPE_EXTENSIONS = {
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/flac": ".flac",
    "audio/x-flac": ".flac",
    "audio/ogg": ".ogg",
    "audio/mp4": ".m4a",
}


def isolate_dialog_file(
    source_path: str | Path,
    output_dir: str | Path,
    api_key: str,
    *,
    output_stem: str | None = None,
    base_url: str = DEFAULT_BASE_URL,
    max_retries: int = 4,
    base_delay: float = 2.0,
    timeout: httpx.Timeout = DEFAULT_TIMEOUT,
    on_retry: RetryCallback | None = None,
    cancel_event=None,
    client: httpx.Client | None = None,
) -> Path:
    """Upload media and atomically save the native isolated-dialog response.

    The source and response are streamed rather than held in memory. The response
    extension is selected from its content type and first bytes, with MP3 as the
    conservative fallback used by ElevenLabs' own integration.
    """
    _require_secure(base_url)
    source = Path(source_path)
    target_dir = Path(output_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    stem = output_stem or f"{source.stem}_DX"
    url = base_url.rstrip("/") + VOICE_ISOLATION_PATH
    headers = {"xi-api-key": api_key}

    try:
        from ..logging_setup import get_logger

        get_logger().info(
            "upload host=%s file=%s feature=voice_isolation",
            urlparse(base_url).hostname,
            source.name,
        )
    except Exception:
        pass

    def canceled() -> bool:
        return cancel_event is not None and cancel_event.is_set()

    def wait(delay: float) -> None:
        if cancel_event is not None:
            if cancel_event.wait(timeout=delay):
                raise TransferCanceled("Canceled")
        else:
            time.sleep(delay)

    owns_client = client is None
    client = client or httpx.Client(timeout=timeout)
    try:
        attempt = 0
        while True:
            attempt += 1
            if canceled():
                raise TransferCanceled("Canceled")
            temp_path: Path | None = None
            try:
                media_type = mimetypes.guess_type(source.name)[0] or "application/octet-stream"
                with source.open("rb") as source_file:
                    files = {"audio": (source.name, source_file, media_type)}
                    with client.stream("POST", url, headers=headers, files=files) as resp:
                        if resp.status_code != 200:
                            message = _stream_error_text(resp)
                            if resp.status_code in (401, 403):
                                raise ElevenLabsAuthError(message)
                            if resp.status_code == 413:
                                raise ElevenLabsApiError(
                                    "File too large for ElevenLabs Voice Isolation "
                                    "(over the 500 MB limit).",
                                    status_code=413,
                                )
                            if resp.status_code in RETRIABLE_STATUS and attempt <= max_retries:
                                delay = _retry_after(resp) or _backoff(attempt, base_delay)
                                _emit(on_retry, attempt, max_retries, delay, f"HTTP {resp.status_code}")
                                wait(delay)
                                continue
                            raise ElevenLabsApiError(message, status_code=resp.status_code)

                        content_type = resp.headers.get("content-type", "")
                        normalized_content_type = (
                            content_type.lower().split(";", 1)[0].strip()
                        )
                        if normalized_content_type in {
                            "application/json",
                            "text/json",
                        }:
                            raise ElevenLabsApiError(
                                "ElevenLabs returned JSON instead of isolated audio."
                            )

                        fd, raw_temp = tempfile.mkstemp(
                            dir=target_dir, prefix=f".{stem}.", suffix=".part"
                        )
                        temp_path = Path(raw_temp)
                        first = b""
                        total = 0
                        with os.fdopen(fd, "wb") as output_file:
                            for chunk in resp.iter_bytes():
                                if canceled():
                                    raise TransferCanceled("Canceled")
                                if not chunk:
                                    continue
                                if len(first) < 16:
                                    first += chunk[: 16 - len(first)]
                                output_file.write(chunk)
                                total += len(chunk)
                            output_file.flush()
                            os.fsync(output_file.fileno())

                        if total == 0:
                            raise ElevenLabsApiError(
                                "ElevenLabs returned an empty Voice Isolation response."
                            )
                        extension = _audio_extension(content_type, first)
                        target = target_dir / f"{stem}{extension}"
                        os.replace(temp_path, target)
                        temp_path = None
                        return target
            except (ElevenLabsAuthError, TransferCanceled):
                raise
            except httpx.HTTPError as exc:
                if attempt > max_retries:
                    raise ElevenLabsApiError(
                        f"Network error after {max_retries} retries: {exc}"
                    ) from exc
                delay = _backoff(attempt, base_delay)
                _emit(on_retry, attempt, max_retries, delay, f"network error: {exc}")
                wait(delay)
                continue
            finally:
                if temp_path is not None:
                    temp_path.unlink(missing_ok=True)
    finally:
        if owns_client:
            client.close()


def _audio_extension(content_type: str, first: bytes) -> str:
    normalized = content_type.lower().split(";", 1)[0].strip()
    if normalized in _CONTENT_TYPE_EXTENSIONS:
        return _CONTENT_TYPE_EXTENSIONS[normalized]
    if first.startswith(b"RIFF") and first[8:12] == b"WAVE":
        return ".wav"
    if first.startswith(b"fLaC"):
        return ".flac"
    if first.startswith(b"OggS"):
        return ".ogg"
    if first.startswith(b"ID3") or (len(first) >= 2 and first[0] == 0xFF and first[1] & 0xE0 == 0xE0):
        return ".mp3"
    if len(first) >= 8 and first[4:8] == b"ftyp":
        return ".m4a"
    return ".mp3"


def _stream_error_text(resp: httpx.Response) -> str:
    """Read only a small error prefix so unexpected bodies cannot fill memory/logs."""
    payload = bytearray()
    for chunk in resp.iter_bytes():
        if len(payload) >= 4096:
            break
        payload.extend(chunk[: 4096 - len(payload)])
    text = bytes(payload).decode("utf-8", errors="replace")
    try:
        body = json.loads(text)
        detail = body.get("detail", body) if isinstance(body, dict) else body
        detail_text = str(detail)
    except Exception:
        detail_text = text
    return f"HTTP {resp.status_code}: {detail_text[:200]}"
