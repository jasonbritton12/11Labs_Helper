"""App-managed transcript history.

The canonical transcription JSON is stored here — in the app support directory,
NOT alongside the user's deliverables — so it survives the user deleting/moving
their output files and can drive a free (no-API) re-export. Keyed by job id.
"""

from __future__ import annotations

from pathlib import Path

from .config import app_support_dir
from .elevenlabs.models import TranscriptionResult


def history_dir() -> Path:
    d = app_support_dir() / "history"
    d.mkdir(parents=True, exist_ok=True)
    return d


def history_path(job_id: str) -> Path:
    return history_dir() / f"{job_id}.json"


def save_history(result: TranscriptionResult, job_id: str) -> Path:
    """Persist the canonical result to the app history space; return its path."""
    path = history_path(job_id)
    path.write_text(result.model_dump_json(indent=2))
    return path


def load_history(job_id: str) -> TranscriptionResult | None:
    path = history_path(job_id)
    if not path.exists():
        return None
    return load_history_file(path)


def load_history_file(path: str | Path) -> TranscriptionResult:
    return TranscriptionResult.model_validate_json(Path(path).read_text())


def delete_history(job_id: str) -> None:
    history_path(job_id).unlink(missing_ok=True)
