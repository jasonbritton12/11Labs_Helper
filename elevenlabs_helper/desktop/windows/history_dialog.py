"""Transcript History — browse/recover past jobs and re-export or purge them (J3)."""

from __future__ import annotations

import subprocess
from pathlib import Path

from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...engine.jobs.models import Job
from ..reexport_action import reexport_with_prompt

_COLUMNS = ["File", "Date", "Status", "Actions"]


class HistoryDialog(QDialog):
    def __init__(self, engine, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.setWindowTitle("Transcript History")
        self.resize(720, 460)
        root = QVBoxLayout(self)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search by file name…")
        self.search.textChanged.connect(self._reload)
        root.addWidget(self.search)

        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(_COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        for i in range(1, len(_COLUMNS)):
            header.setSectionResizeMode(i, QHeaderView.ResizeToContents)
        root.addWidget(self.table)

        self._reload()

    def _matching_jobs(self) -> list[Job]:
        needle = self.search.text().strip().lower()
        jobs = self.engine.all_jobs()
        if needle:
            jobs = [j for j in jobs if needle in j.source_name.lower()]
        return list(reversed(jobs))  # newest first for browsing

    def _reload(self) -> None:
        self.table.setRowCount(0)
        for job in self._matching_jobs():
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

        has_history = bool(job.history_json and Path(job.history_json).exists())
        reexport = QPushButton("Re-export")
        reexport.setEnabled(has_history)
        reexport.setToolTip("Regenerate deliverables — no API cost" if has_history
                            else "No saved transcript to re-export from")
        reexport.clicked.connect(lambda: self._reexport(job.id))
        lay.addWidget(reexport)

        reveal = QPushButton("Reveal")
        reveal.clicked.connect(lambda: self._reveal(job))
        lay.addWidget(reveal)

        delete = QPushButton("Delete…")
        delete.setToolTip("Permanently delete this transcript (removes the recoverable copy)")
        delete.clicked.connect(lambda: self._delete(job))
        lay.addWidget(delete)
        lay.addStretch()
        return w

    def _reexport(self, job_id: str) -> None:
        job = self.engine.store.get(job_id)
        if job is not None:
            reexport_with_prompt(self, self.engine, job)

    def _reveal(self, job: Job) -> None:
        target = Path(job.output_dir)
        if target.exists():
            subprocess.run(["open", str(target)], check=False)
        else:
            QMessageBox.information(self, "Folder missing", "The output folder no longer exists.")

    def _delete(self, job: Job) -> None:
        if QMessageBox.question(
            self, "Delete permanently?",
            f"Permanently delete the saved transcript for “{job.source_name}”?\n\n"
            "This removes the recoverable copy — re-export will no longer be possible "
            "without re-transcribing (which costs credits).",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        ) == QMessageBox.Yes:
            self.engine.delete_permanently(job.id)
            self._reload()
