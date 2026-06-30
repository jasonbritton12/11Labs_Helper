"""Synchronous ElevenLabs Speech-to-Text client with retry/backoff.

V1 uses synchronous requests: the user-supplied audio file is uploaded directly,
so the request completes without needing webhook/async results.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

import httpx

from ..config import TranscriptionParams
from .models import TranscriptionResult

DEFAULT_BASE_URL = "https://api.elevenlabs.io"
STT_PATH = "/v1/speech-to-text"
USER_PATH = "/v1/user"

# Generous read timeout: transcription of a long file can take a while.
DEFAULT_TIMEOUT = httpx.Timeout(connect=30.0, read=1800.0, write=1800.0, pool=30.0)

RETRIABLE_STATUS = {429, 500, 502, 503, 504}

# Called as on_retry(attempt, max_retries, delay_secs, reason).
RetryCallback = Callable[[int, int, float, str], None]


class ElevenLabsError(RuntimeError):
    """Base error."""


class ElevenLabsAuthError(ElevenLabsError):
    """401/403 — bad or missing key. Not retried."""


class ElevenLabsApiError(ElevenLabsError):
    """Permanent (4xx other than auth/rate-limit) or exhausted retries."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class TransferCanceled(ElevenLabsError):
    """Raised when a cancel_event fires at a retry boundary."""


_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _require_secure(base_url: str) -> None:
    """Refuse to send the API key over a non-HTTPS endpoint (except loopback for tests)."""
    parsed = urlparse(base_url)
    if parsed.scheme == "https":
        return
    if parsed.hostname in _LOOPBACK_HOSTS:
        return
    raise ElevenLabsApiError(
        f"Refusing to send credentials over an insecure URL: {base_url!r} "
        "(use https://)."
    )


def validate_key(
    api_key: str, *, base_url: str = DEFAULT_BASE_URL, timeout: float = 10.0
) -> tuple[str, str]:
    """Cheaply check a key before the user commits to a job.

    Returns ``(status, message)`` where status is one of:
      - ``"valid"``     — authenticated successfully
      - ``"invalid"``   — the key was rejected (401/403)
      - ``"unverified"``— couldn't reach the API (offline/timeout); allow but warn
    """
    if not api_key.strip():
        return "invalid", "Enter an API key."
    try:
        _require_secure(base_url)
    except ElevenLabsApiError as exc:
        return "invalid", str(exc)
    url = base_url.rstrip("/") + USER_PATH
    try:
        resp = httpx.get(url, headers={"xi-api-key": api_key.strip()}, timeout=timeout)
    except httpx.HTTPError as exc:
        return "unverified", f"Couldn't reach ElevenLabs to verify the key ({exc})."
    if resp.status_code == 200:
        return "valid", "Key verified."
    if resp.status_code in (401, 403):
        body = ""
        try:
            body = json.dumps(resp.json()).lower()
        except Exception:
            body = (resp.text or "").lower()
        # A definitively bad key reports invalid_api_key — block that.
        if "invalid_api_key" in body or "could not validate" in body:
            return "invalid", "ElevenLabs rejected this key. Check that you copied it correctly."
        # A *scoped* key (e.g. speech-to-text only) authenticates but lacks access to
        # /v1/user (missing_permissions). That key still works for transcription.
        if "permission" in body:
            return "valid", "Key accepted (scoped key — limited to its permitted endpoints)."
        # Anything else ambiguous: don't block a possibly-working key.
        return "unverified", "Couldn't fully verify the key here; it will be tried on your first job."
    return "unverified", f"Unexpected response verifying the key (HTTP {resp.status_code})."


def friendly_error(message: str | None) -> str:
    """Map a raw engine/HTTP error into concise, actionable user-facing copy."""
    if not message:
        return "Failed."
    low = message.lower()
    if "no elevenlabs api key" in low or "no api key" in low:
        return "Add your ElevenLabs API key in Settings."
    if "401" in low or "403" in low or "invalid_api_key" in low or "rejected this key" in low:
        return "Invalid API key — update it in Settings."
    if "429" in low or "rate" in low:
        return "Rate-limited by ElevenLabs — try again shortly."
    if "network" in low or "timeout" in low or "timed out" in low or "connect" in low:
        return "Network problem — check your connection and retry."
    if "not found" in low:
        return "Source file not found — it may have moved or been deleted."
    if "too large" in low or ("over the" in low and "limit" in low):
        return "File is too large for ElevenLabs (over the size limit)."
    if "exceeds elevenlabs limits" in low:
        return "File exceeds ElevenLabs limits (size or duration)."
    if "couldn't write output" in low or "can't read" in low:
        return "Couldn't write output — check the folder permissions/space."
    return "Failed — hover for details."


def _build_data(params: TranscriptionParams) -> dict[str, str]:
    data: dict[str, str] = {
        "model_id": params.model_id,
        "diarize": str(params.diarize).lower(),
        "timestamps_granularity": params.timestamps_granularity,
        "tag_audio_events": str(params.tag_audio_events).lower(),
    }
    if params.language_code:
        data["language_code"] = params.language_code
    if params.num_speakers is not None:
        data["num_speakers"] = str(params.num_speakers)
    return data


def transcribe_file(
    audio_path: str | Path,
    params: TranscriptionParams,
    api_key: str,
    *,
    base_url: str = DEFAULT_BASE_URL,
    max_retries: int = 4,
    base_delay: float = 2.0,
    timeout: httpx.Timeout = DEFAULT_TIMEOUT,
    on_retry: RetryCallback | None = None,
    cancel_event=None,
    client: httpx.Client | None = None,
) -> TranscriptionResult:
    """Upload ``audio_path`` to Scribe and return the parsed result.

    The file is streamed from disk (never loaded fully into memory). Transient
    failures (429/5xx/network) retry with exponential backoff; ``cancel_event``
    (a ``threading.Event``) aborts at retry boundaries. Raises
    :class:`ElevenLabsAuthError` on 401/403, :class:`ElevenLabsApiError` on
    permanent failures or exhausted retries, and :class:`TransferCanceled` if
    canceled.
    """
    _require_secure(base_url)
    audio_path = Path(audio_path)
    data = _build_data(params)
    headers = {"xi-api-key": api_key}
    url = base_url.rstrip("/") + STT_PATH
    # Audit the egress destination (host only — never the key or file content).
    try:
        from ..logging_setup import get_logger

        get_logger().info("upload host=%s file=%s", urlparse(base_url).hostname, audio_path.name)
    except Exception:
        pass

    def _canceled() -> bool:
        return cancel_event is not None and cancel_event.is_set()

    def _wait(delay: float) -> None:
        # Interruptible sleep: cancel during a backoff wait aborts promptly.
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
            if _canceled():
                raise TransferCanceled("Canceled")
            try:
                with audio_path.open("rb") as fh:
                    files = {"file": (audio_path.name, fh, "application/octet-stream")}
                    resp = client.post(url, headers=headers, data=data, files=files)
            except httpx.HTTPError as exc:
                if attempt > max_retries:
                    raise ElevenLabsApiError(f"Network error after {max_retries} retries: {exc}")
                _emit(on_retry, attempt, max_retries, _backoff(attempt, base_delay), f"network error: {exc}")
                _wait(_backoff(attempt, base_delay))
                continue

            if resp.status_code == 200:
                return TranscriptionResult.model_validate(resp.json())

            if resp.status_code in (401, 403):
                raise ElevenLabsAuthError(_error_text(resp))

            if resp.status_code == 413:
                raise ElevenLabsApiError(
                    "File too large for ElevenLabs (over the size limit).", status_code=413
                )

            if resp.status_code in RETRIABLE_STATUS and attempt <= max_retries:
                delay = _retry_after(resp) or _backoff(attempt, base_delay)
                _emit(on_retry, attempt, max_retries, delay, f"HTTP {resp.status_code}")
                _wait(delay)
                continue

            raise ElevenLabsApiError(_error_text(resp), status_code=resp.status_code)
    finally:
        if owns_client:
            client.close()


def _backoff(attempt: int, base_delay: float) -> float:
    return base_delay * (2 ** (attempt - 1))


def _emit(on_retry, attempt, max_retries, delay, reason):
    if on_retry is not None:
        on_retry(attempt, max_retries, delay, reason)


def _retry_after(resp: httpx.Response) -> float | None:
    value = resp.headers.get("retry-after")
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _error_text(resp: httpx.Response) -> str:
    # Keep it concise: only the code + a short detail snippet is persisted to the DB,
    # so we don't store large/sensitive response bodies (SSR-007).
    try:
        body = resp.json()
        detail = body.get("detail", body)
        return f"HTTP {resp.status_code}: {str(detail)[:200]}"
    except Exception:
        return f"HTTP {resp.status_code}: {resp.text[:200]}"
