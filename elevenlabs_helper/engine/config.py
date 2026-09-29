"""Central configuration: ElevenLabs limits and persisted settings.

This module is UI-free so it can be imported by the desktop app, the CLI, and any
cloud/SDVI-Rally worker alike. V1 uploads a user-supplied audio file directly
(no conversion); see the roadmap for FFmpeg conversion + segmentation.
"""

from __future__ import annotations

import os
import sys
import tempfile
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, PrivateAttr, field_validator, model_validator

from .captions import CaptionExportOptions, CaptionTimingMode, get_caption_profile

# --- ElevenLabs Scribe hard limits (verified June 2026) ----------------------
ELEVENLABS_MAX_FILE_BYTES: int = 5 * 1024**3        # 5 GB
ELEVENLABS_MAX_DURATION_SECS: float = 10 * 3600.0   # ~10 hours

# Voice Isolation has a separate, much smaller upload envelope.
VOICE_ISOLATION_MAX_FILE_BYTES: int = 500 * 1024**2  # 500 MB
VOICE_ISOLATION_MAX_DURATION_SECS: float = 60 * 60.0 # 1 hour


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
    explicit = os.environ.get("ELEVENLABS_HELPER_DATA_DIR")
    if explicit:
        base = Path(explicit).expanduser()
    elif sys.platform == "darwin":
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
    # Caption defaults. ``readable_subtitles`` below remains a compatibility property
    # for callers that have not moved to the explicit timing enum yet.
    caption_timing_mode: CaptionTimingMode = CaptionTimingMode.HOUSE
    caption_profile_id: str = "house-english-v1"
    max_retries: int = 4
    retry_base_delay_secs: float = 2.0

    _load_warning: str | None = PrivateAttr(default=None)

    @model_validator(mode="before")
    @classmethod
    def _adapt_legacy_constructor_values(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        data = dict(value)
        if "caption_timing_mode" not in data and "readable_subtitles" in data:
            data["caption_timing_mode"] = (
                CaptionTimingMode.HOUSE.value
                if data["readable_subtitles"]
                else CaptionTimingMode.SOURCE.value
            )
        data.pop("readable_subtitles", None)
        return data

    @property
    def readable_subtitles(self) -> bool:
        """Deprecated compatibility view of the explicit caption timing mode."""
        return self.caption_timing_mode == CaptionTimingMode.HOUSE

    @readable_subtitles.setter
    def readable_subtitles(self, value: bool) -> None:
        self.caption_timing_mode = (
            CaptionTimingMode.HOUSE if value else CaptionTimingMode.SOURCE
        )

    @property
    def load_warning(self) -> str | None:
        """Diagnostic from the most recent load, excluded from persisted settings."""
        return self._load_warning

    # --- persistence ---------------------------------------------------------
    @classmethod
    def load(cls) -> "EngineSettings":
        path = _config_path()
        if not path.exists():
            return cls()
        try:
            import json

            raw = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("settings root must be an object")
            payload = dict(raw)
            has_new_mode = "caption_timing_mode" in payload
            has_new_profile = "caption_profile_id" in payload
            if not has_new_mode:
                if "readable_subtitles" in payload:
                    payload["caption_timing_mode"] = (
                        CaptionTimingMode.HOUSE.value
                        if payload["readable_subtitles"]
                        else CaptionTimingMode.SOURCE.value
                    )
                else:
                    # Preserve the old saved default when neither field exists.
                    payload["caption_timing_mode"] = CaptionTimingMode.SOURCE.value
            if not has_new_profile:
                payload["caption_profile_id"] = "house-english-v1"
            settings = cls.model_validate(payload)
            get_caption_profile(settings.caption_profile_id)
            if not has_new_mode or not has_new_profile or "readable_subtitles" in raw:
                settings._load_warning = "Legacy caption settings were migrated in memory."
            return settings
        except Exception as exc:
            # Corrupt or invalid settings should never block startup; retain a
            # diagnostic without rewriting the user's file during a read.
            settings = cls()
            settings._load_warning = f"Settings could not be loaded; defaults were used ({exc})."
            return settings

    def save(self) -> None:
        path = _config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary: Path | None = None
        try:
            fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
            temporary = Path(name)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(self.model_dump_json(indent=2))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
            temporary = None
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)


def resolve_caption_options(
    settings: EngineSettings,
    *,
    explicit: CaptionExportOptions | dict[str, Any] | None = None,
    legacy_readable: bool | None = None,
) -> CaptionExportOptions:
    """Resolve one immutable caption option snapshot using documented precedence."""
    if explicit is not None:
        options = (
            explicit
            if isinstance(explicit, CaptionExportOptions)
            else CaptionExportOptions.model_validate(explicit)
        )
        if legacy_readable is not None:
            legacy_mode = CaptionTimingMode.HOUSE if legacy_readable else CaptionTimingMode.SOURCE
            if options.timing_mode != legacy_mode:
                raise ValueError(
                    "caption timing options disagree: explicit timing_mode and "
                    "legacy readable_subtitles must resolve to the same mode"
                )
        get_caption_profile(options.profile_id, options.profile_version)
        return options.model_copy(deep=True)

    mode = (
        CaptionTimingMode.HOUSE if legacy_readable
        else CaptionTimingMode.SOURCE if legacy_readable is not None
        else settings.caption_timing_mode
    )
    profile = get_caption_profile(settings.caption_profile_id)
    return CaptionExportOptions(
        timing_mode=mode,
        profile_id=profile.profile_id,
        profile_version=profile.profile_version,
    )


def output_dir_for(source: Path, settings: EngineSettings) -> Path:
    """Resolve the per-source output subfolder (…/<stem>/) for a given source file."""
    root = settings.output_root if settings.output_root is not None else source.parent
    return Path(root) / source.stem
