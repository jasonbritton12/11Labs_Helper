"""SQLite-backed job persistence.

Stores each job as a JSON document (forward-compatible with model changes) plus
a few promoted columns for ordering/filtering. Safe to share across threads.
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from ..config import database_path
from .models import Job, JobStatus

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    data TEXT NOT NULL,
    archived INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_jobs_created ON jobs(created_at);
"""


class JobStore:
    def __init__(self, db_path: str | Path | None = None):
        self._path = str(db_path or database_path())
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self._path, check_same_thread=False)
        self._conn.executescript(_SCHEMA)
        # Migrate DBs created before the archived column existed.
        try:
            self._conn.execute("ALTER TABLE jobs ADD COLUMN archived INTEGER NOT NULL DEFAULT 0")
        except sqlite3.OperationalError:
            pass  # column already present
        self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def upsert(self, job: Job) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO jobs (id, status, created_at, updated_at, data, archived)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    status=excluded.status,
                    updated_at=excluded.updated_at,
                    data=excluded.data,
                    archived=excluded.archived
                """,
                (
                    job.id,
                    job.status.value,
                    job.created_at.isoformat(),
                    job.updated_at.isoformat(),
                    job.model_dump_json(),
                    1 if job.archived else 0,
                ),
            )
            self._conn.commit()

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT data FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
        return Job.model_validate_json(row[0]) if row else None

    def list_jobs(
        self, *, limit: int | None = None, archived: bool | None = None
    ) -> list[Job]:
        """List jobs oldest-first. ``archived``: None=all, False=active, True=archived.

        When ``limit`` is set, keeps the newest N (still returned oldest-first).
        """
        where = "" if archived is None else "WHERE archived = ?"
        args: list = [] if archived is None else [1 if archived else 0]
        if limit:
            sql = f"SELECT data FROM jobs {where} ORDER BY created_at DESC LIMIT ?"
            args.append(int(limit))
        else:
            sql = f"SELECT data FROM jobs {where} ORDER BY created_at ASC"
        with self._lock:
            rows = self._conn.execute(sql, tuple(args)).fetchall()
        jobs = [Job.model_validate_json(r[0]) for r in rows]
        if limit:
            jobs.reverse()
        return jobs

    def list_unfinished(self) -> list[Job]:
        """Jobs that were mid-flight when the app last closed (for resume)."""
        active = (
            JobStatus.QUEUED,
            JobStatus.UPLOADING,
            JobStatus.TRANSCRIBING,
            JobStatus.ISOLATING,
            JobStatus.EXPORTING,
            JobStatus.RETRYING,
        )
        placeholders = ",".join("?" for _ in active)
        with self._lock:
            rows = self._conn.execute(
                f"SELECT data FROM jobs WHERE status IN ({placeholders}) ORDER BY created_at ASC",
                tuple(s.value for s in active),
            ).fetchall()
        return [Job.model_validate_json(r[0]) for r in rows]

    def delete(self, job_id: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
            self._conn.commit()
