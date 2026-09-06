"""Transcript History — browse/recover past jobs and re-export or purge them (J3)."""

from __future__ import annotations

import subprocess
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...engine.jobs.models import Job, JobStatus, JobType
from ..reexport_action import reexport_with_prompt

_COLUMNS = ["File", "Date", "Status", "Actions"]


class HistoryDialog(QDialog):
    def __init__(self, engine, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.setWindowTitle("Job History")
        self.resize(740, 480)
        root = QVBoxLayout(self)

        intro = QLabel(
            "Past transcription and dialog-isolation jobs, including ones cleared "
            "from the main list."
        )
        intro.setWordWrap(True)
        root.addWidget(intro)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search by file name…")
        # Debounce so we don't rebuild the whole table on every keystroke (SER-021).
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(200)
        self._debounce.timeout.connect(self._reload)
        self.search.textChanged.connect(lambda: self._debounce.start())
        root.addWidget(self.search)

        # Stack: table when there are results, an empty-state message otherwise.
        self.stack = QStackedWidget()
        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(_COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        for i in range(1, len(_COLUMNS)):
            header.setSectionResizeMode(i, QHeaderView.ResizeToContents)
        self.empty = QLabel("No jobs yet.\nProcess a file and it will appear here.")
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setStyleSheet("color: gray;")
        self.stack.addWidget(self.table)
        self.stack.addWidget(self.empty)
        root.addWidget(self.stack)

        self._reload()

    def _matching_jobs(self) -> list[Job]:
        needle = self.search.text().strip().lower()
        jobs = self.engine.all_jobs()
        if needle:
            jobs = [j for j in jobs if needle in j.source_name.lower()]
        return list(reversed(jobs))  # newest first for browsing

    def _reload(self) -> None:
        jobs = self._matching_jobs()
        self.stack.setCurrentWidget(self.table if jobs else self.empty)
        if not jobs:
            no_search = not self.search.text().strip()
            self.empty.setText(
                "No jobs yet.\nProcess a file and it will appear here."
                if no_search else "No jobs match your search."
            )
        self.table.setRowCount(0)
        for job in jobs:
            self._add_row(job)

    def _add_row(self, job: Job) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(job.source_name))
        self.table.setItem(row, 1, QTableWidgetItem(job.created_at.astimezone().strftime("%Y-%m-%d %H:%M")))
        self.table.setItem(row, 2, QTableWidgetItem(job.status.value.capitalize()))
        self.table.setCellWidget(row, 3, self._actions(job))

    def _actions(self, job: Job) -> QWidget:
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(2, 2, 2, 2)
        lay.setSpacing(4)

        if job.status == JobStatus.DONE and job.job_type == JobType.TRANSCRIPTION:
            has_history = bool(job.history_json and Path(job.history_json).exists())
            reexport = QPushButton("Re-export…")
            reexport.setEnabled(has_history)
            reexport.setToolTip("Regenerate deliverables — no API cost" if has_history
                                else "No saved transcript to re-export from")
            reexport.clicked.connect(lambda: self._reexport(job.id))
            lay.addWidget(reexport)
        elif job.status == JobStatus.FAILED:
            requeue = QPushButton("Requeue")
            action = "dialog isolation" if job.job_type == JobType.VOICE_ISOLATION else "transcription"
            requeue.setToolTip(f"Try {action} again (uses credits)")
            requeue.clicked.connect(lambda: self._requeue(job.id))
            lay.addWidget(requeue)

        reveal = QPushButton("Reveal")
        reveal.clicked.connect(lambda: self._reveal(job))
        lay.addWidget(reveal)

        delete = QPushButton("Delete…")
        delete.setToolTip("Permanently delete this app history record")
        delete.clicked.connect(lambda: self._delete(job))
        lay.addWidget(delete)
        lay.addStretch()
        return w

    def _reexport(self, job_id: str) -> None:
        job = self.engine.store.get(job_id)
        if job is not None:
            reexport_with_prompt(self, self.engine, job)

    def _requeue(self, job_id: str) -> None:
        job = self.engine.store.get(job_id)
        self.engine.requeue(job_id)
        action = (
            "dialog isolation"
            if job and job.job_type == JobType.VOICE_ISOLATION
            else "transcription"
        )
        QMessageBox.information(self, "Requeued", f"The job was re-queued for {action}.")
        self._reload()

    def _reveal(self, job: Job) -> None:
        target = Path(job.output_dir)
        if target.exists():
            subprocess.run(["open", str(target)], check=False)
        else:
            QMessageBox.information(self, "Folder missing", "The output folder no longer exists.")

    def _delete(self, job: Job) -> None:
        if QMessageBox.question(
            self, "Delete permanently?",
            f"Permanently delete the app history record for “{job.source_name}”?\n\n"
            "Files already saved in the output folder remain on disk. Transcript "
            "re-export will no longer be available for a deleted transcription record.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        ) == QMessageBox.Yes:
            self.engine.delete_permanently(job.id)
            self._reload()
