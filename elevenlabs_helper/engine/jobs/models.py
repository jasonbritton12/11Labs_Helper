"""Job and status models."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field

from ..config import Deliverable, TranscriptionParams


class JobStatus(str, Enum):
    STAGED = "staged"        # added but not yet run — nothing hits the API until "Run"
    QUEUED = "queued"
    UPLOADING = "uploading"
    TRANSCRIBING = "transcribing"
    EXPORTING = "exporting"
    DONE = "done"
    FAILED = "failed"
    RETRYING = "retrying"
    CANCELED = "canceled"


TERMINAL_STATUSES = {JobStatus.DONE, JobStatus.FAILED, JobStatus.CANCELED}


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Job(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    source_path: str
    output_dir: str
    params: TranscriptionParams = Field(default_factory=TranscriptionParams)
    deliverables: list[Deliverable] = Field(default_factory=list)

    status: JobStatus = JobStatus.QUEUED
    progress: float = 0.0          # 0..1 coarse progress
    message: str = ""
    error: str | None = None
    attempts: int = 0

    # actual file facts (shown in the UI; no conversion in V1)
    size_bytes: int | None = None
    duration_secs: float | None = None
    # set True when the user has acknowledged an over-limit file and wants to try anyway
    acknowledged_oversize: bool = False

    artifacts: dict[str, str] = Field(default_factory=dict)  # type -> path
    history_json: str | None = None  # app-space canonical JSON path (for re-export)
    archived: bool = False  # hidden from the main queue list but kept for re-export

    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)

    @property
    def source_name(self) -> str:
        from pathlib import Path

        return Path(self.source_path).name

    def touch(self) -> None:
        self.updated_at = _now()
