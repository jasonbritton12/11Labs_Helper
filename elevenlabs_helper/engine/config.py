"""Central configuration: ElevenLabs limits and persisted settings.

This module is UI-free so it can be imported by the desktop app, the CLI, and any
cloud/SDVI-Rally worker alike. V1 uploads a user-supplied audio file directly
(no conversion); see the roadmap for FFmpeg conversion + segmentation.
"""

from __future__ import annotations

import os
import sys
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field, field_validator

# --- ElevenLabs Scribe hard limits (verified June 2026) ----------------------
ELEVENLABS_MAX_FILE_BYTES: int = 5 * 1024**3        # 5 GB
ELEVENLABS_MAX_DURATION_SECS: float = 10 * 3600.0   # ~10 hours


class Deliverable(str, Enum):
    SRT = "srt"
    VTT = "vtt"
    DOCX = "docx"
    JSON = "json"          # raw/canonical; internal by default, exposable later


# Default user-facing deliverables for V1.
DEFAULT_DELIVERABLES: tuple[Deliverable, ...] = (
    Deliverable.SRT,
    Deliverable.VTT,
    Deliverable.DOCX,
)

APP_NAME = "ElevenLabsHelper"
DEFAULT_STT_MODEL = "scribe_v2"


def app_support_dir() -> Path:
    """Per-user app data directory (config + SQLite db). macOS-first, with fallbacks."""
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / APP_NAME
    elif os.name == "nt":  # pragma: no cover - not a target platform yet
        base = Path(os.environ.get("APPDATA", Path.home())) / APP_NAME
    else:  # pragma: no cover - linux/containers
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / APP_NAME
    base.mkdir(parents=True, exist_ok=True)
    return base


def database_path() -> Path:
    return app_support_dir() / "jobs.db"


def _config_path() -> Path:
    return app_support_dir() / "settings.json"


class TranscriptionParams(BaseModel):
    """Per-job Scribe parameters. Defaults match the locked V1 product decisions."""

    model_id: str = DEFAULT_STT_MODEL
    diarize: bool = True
    timestamps_granularity: str = "word"
    tag_audio_events: bool = True
    language_code: str | None = None  # None => auto-detect
    num_speakers: int | None = None   # None => let Scribe decide (up to 32)

    @field_validator("num_speakers")
    @classmethod
    def _clamp_speakers(cls, v: int | None) -> int | None:
        # Scribe accepts 1..32; clamp so an out-of-range value never causes a 422.
        if v is None:
            return None
        return max(1, min(32, v))


class EngineSettings(BaseModel):
    """User-configurable defaults, persisted to settings.json."""

    output_root: Path | None = None  # None => write alongside each source file
    deliverables: list[Deliverable] = Field(default_factory=lambda: list(DEFAULT_DELIVERABLES))
    transcription: TranscriptionParams = Field(default_factory=TranscriptionParams)
    keep_raw_json: bool = True  # write <stem>.raw.json (full word-level data) to disk
    max_retries: int = 4
    retry_base_delay_secs: float = 2.0

    # --- persistence ---------------------------------------------------------
    @classmethod
    def load(cls) -> "EngineSettings":
        path = _config_path()
        if path.exists():
            try:
                return cls.model_validate_json(path.read_text())
            except Exception:
                # Corrupt settings should never block startup; fall back to defaults.
                return cls()
        return cls()

    def save(self) -> None:
        _config_path().write_text(self.model_dump_json(indent=2))


def output_dir_for(source: Path, settings: EngineSettings) -> Path:
    """Resolve the per-source output subfolder (…/<stem>/) for a given source file."""
    root = settings.output_root if settings.output_root is not None else source.parent
    return Path(root) / source.stem
