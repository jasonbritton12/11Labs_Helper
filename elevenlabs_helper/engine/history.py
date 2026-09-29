"""App-managed transcript history.

The canonical transcription JSON is stored here — in the app support directory,
NOT alongside the user's deliverables — so it survives the user deleting/moving
their output files and can drive a free (no-API) re-export. Keyed by job id.
"""

from __future__ import annotations

import time
from pathlib import Path

from .elevenlabs.models import TranscriptionResult


def history_dir() -> Path:
    # Resolve lazily because caption sidecars import this module while the
    # settings module itself imports the caption contracts.
    from .config import app_support_dir

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


_PRIVATE_RECORD_SUFFIXES = (
    ".edits.json",
    ".caption-overlay.json",
    ".caption-approvals.json",
)


def delete_private_records(job_id: str) -> None:
    """Delete only app-managed records associated with one canonical history ID."""

    # Kept local to avoid the captions/history import cycle.
    from .edits import delete_edits
    from .captions.overlays import delete_caption_approvals, delete_caption_overlay

    delete_edits(job_id)
    delete_caption_overlay(job_id)
    delete_caption_approvals(job_id)


def delete_history_group(job_id: str) -> None:
    """Remove a canonical input and every managed private companion record."""

    delete_history(job_id)
    delete_private_records(job_id)


def _canonical_history_files() -> list[Path]:
    return [
        path
        for path in history_dir().glob("*.json")
        if not path.name.endswith(_PRIVATE_RECORD_SUFFIXES)
    ]


def prune_history_groups(days: int) -> set[str]:
    """Prune aged managed history as job groups and remove managed orphans.

    This deliberately scans only the app-private history directory and the three
    exact private-record suffixes.  User output JSON and caption sidecars are
    never discovered or removed here.
    """

    removed: set[str] = set()
    if days > 0:
        cutoff = time.time() - days * 86400
        for path in _canonical_history_files():
            try:
                if path.stat().st_mtime < cutoff:
                    job_id = path.name[:-5]
                    delete_history_group(job_id)
                    removed.add(job_id)
            except OSError:
                pass
    for suffix in _PRIVATE_RECORD_SUFFIXES:
        for path in history_dir().glob(f"*{suffix}"):
            job_id = path.name[: -len(suffix)]
            if not history_path(job_id).exists():
                try:
                    path.unlink()
                except OSError:
                    pass
    return removed


def prune_history(days: int) -> int:
    """Backward-compatible count of aged canonical history groups removed."""

    return len(prune_history_groups(days))
