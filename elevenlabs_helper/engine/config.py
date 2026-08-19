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
    DUB_CSV = "dub_csv"    # ElevenLabs Dubbing Studio "Manual Dub" script (speaker/timing/text)


# Default user-facing deliverables. (DOCX and JSON are opt-in; the canonical JSON
# is always kept in the app history space — see keep_history_json — so JSON here is
# only an extra user-facing copy in the output folder.)
DEFAULT_DELIVERABLES: tuple[Deliverable, ...] = (
    Deliverable.SRT,
    Deliverable.VTT,
)

# Single source of truth for deliverable display labels (used by all dialogs).
DELIVERABLE_LABELS: dict[Deliverable, str] = {
    Deliverable.SRT: "SRT",
    Deliverable.VTT: "VTT",
    Deliverable.DOCX: "DOCX",
    Deliverable.JSON: "JSON",
    Deliverable.DUB_CSV: "Dubbing CSV (Manual Dub)",
}

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
    # Silently keep the canonical transcript JSON in the app history space (NOT the
    # user's output folder) so deliverables can be re-exported for free if the user
    # deletes/moves their outputs. Turn off for zero local retention.
    keep_history_json: bool = True
    # Auto-delete history JSONs older than N days (0 = keep forever). Data-minimization
    # option for privacy-sensitive users (SSR-011).
    history_retention_days: int = 0
    # Re-time SRT/VTT cues for reading comfort (min duration / max chars-per-second)
    # instead of raw waveform alignment. The Dubbing CSV always keeps waveform timing.
    readable_subtitles: bool = False
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
