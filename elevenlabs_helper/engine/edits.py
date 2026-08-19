"""User speaker edits, stored as an overlay next to the history JSON.

The canonical transcription result from ElevenLabs is never mutated; speaker
renames and per-cue reassignments live in ``<job_id>.edits.json`` and are applied
on top of the canonical transcript at export time. This keeps re-export free and
repeatable, and lets edits survive re-exports in any format (including the
Dubbing Studio Manual-Dub CSV).

Cue indices refer to the 1-based ``Cue.index`` of the transcript produced by
``exporters.canonical.build_transcript`` — deterministic for a given stored
result, so the overlay stays valid as long as the history JSON is unchanged.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from .history import history_dir


class SpeakerEdits(BaseModel):
    # Display-name overrides, e.g. {"speaker_0": "MARIA"}.
    speaker_names: dict[str, str] = Field(default_factory=dict)
    # Per-cue speaker reassignment: cue index (1-based) -> speaker id.
    cue_overrides: dict[int, str] = Field(default_factory=dict)

    def is_empty(self) -> bool:
        return not self.speaker_names and not self.cue_overrides


def edits_path(job_id: str) -> Path:
    return history_dir() / f"{job_id}.edits.json"


def save_edits(job_id: str, edits: SpeakerEdits) -> Path:
    """Persist the overlay (or remove the file entirely if the edits are empty)."""
    path = edits_path(job_id)
    if edits.is_empty():
        path.unlink(missing_ok=True)
    else:
        path.write_text(edits.model_dump_json(indent=2))
    return path


def load_edits(job_id: str) -> SpeakerEdits | None:
    path = edits_path(job_id)
    if not path.exists():
        return None
    try:
        return SpeakerEdits.model_validate_json(path.read_text())
    except Exception:
        # A corrupt overlay must never block export; fall back to the raw transcript.
        return None


def delete_edits(job_id: str) -> None:
    edits_path(job_id).unlink(missing_ok=True)
