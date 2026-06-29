"""Lightweight media inspection — no FFmpeg.

V1 uploads a user-supplied audio file as-is, so all we need is its size (via
``stat``) and duration (via the pure-Python ``mutagen`` header reader). Both are
fast and require no decoding.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..config import ELEVENLABS_MAX_DURATION_SECS, ELEVENLABS_MAX_FILE_BYTES

SUPPORTED_SUFFIXES = {".mp3"}  # V1 scope; widen on the roadmap


@dataclass(frozen=True)
class MediaInfo:
    size_bytes: int
    duration_secs: float | None  # None when it couldn't be read


def file_size_bytes(path: str | Path) -> int:
    return Path(path).stat().st_size


def audio_duration_secs(path: str | Path) -> float | None:
    """Best-effort duration in seconds; returns None if it can't be parsed."""
    try:
        from mutagen import File as MutagenFile  # noqa: PLC0415
    except Exception:
        return None
    try:
        m = MutagenFile(str(path))
        if m is not None and m.info is not None and getattr(m.info, "length", None):
            return float(m.info.length)
    except Exception:
        return None
    return None


def inspect(path: str | Path) -> MediaInfo:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(p)
    return MediaInfo(size_bytes=p.stat().st_size, duration_secs=audio_duration_secs(p))


def limit_warnings(info: MediaInfo) -> list[str]:
    """Return human-readable reasons the file may be rejected by ElevenLabs (empty if OK)."""
    warnings: list[str] = []
    if info.size_bytes > ELEVENLABS_MAX_FILE_BYTES:
        warnings.append(
            f"File is {human_size(info.size_bytes)} — over the "
            f"{human_size(ELEVENLABS_MAX_FILE_BYTES)} ElevenLabs limit."
        )
    if info.duration_secs is not None and info.duration_secs > ELEVENLABS_MAX_DURATION_SECS:
        warnings.append(
            f"Duration is {human_duration(info.duration_secs)} — over the "
            f"{human_duration(ELEVENLABS_MAX_DURATION_SECS)} ElevenLabs limit."
        )
    return warnings


# --- human-readable helpers (for the GUI and CLI) ---------------------------

def human_size(num_bytes: float) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(num_bytes)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{int(size)} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def human_duration(seconds: float) -> str:
    seconds = int(round(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m:02d}m {s:02d}s"
    if m:
        return f"{m}m {s:02d}s"
    return f"{s}s"
