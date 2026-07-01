"""Main application window: drop area + job queue/history table."""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ...engine import auth
from ...engine.elevenlabs.client import friendly_error
from ...engine.jobs.models import TERMINAL_STATUSES, Job, JobStatus
from ...engine.media.inspect import human_duration, human_size, inspect, limit_warnings
from ...engine.service import Engine
from ..bridge import EngineBridge
from ..reexport_action import reexport_with_prompt
from ..widgets.drop_area import DropArea
from ..widgets.job_options_dialog import JobOptionsDialog
from ..widgets.key_dialog import KeyDialog
from ..widgets.settings_dialog import SettingsDialog
from .history_dialog import HistoryDialog

_COLUMNS = ["File", "Status", "Progress", "Size / Duration", "Actions"]
_BUSY_STATUSES = {JobStatus.UPLOADING, JobStatus.TRANSCRIBING}


class MainWindow(QMainWindow):
    def __init__(self, engine: Engine, bridge: EngineBridge):
        super().__init__()
        self.engine = engine
        self.bridge = bridge
        self._rows: dict[str, int] = {}  # job_id -> row index
        self._busy_since: dict[str, float] = {}  # job_id -> monotonic start of busy state
        self._busy_base: dict[str, str] = {}     # job_id -> base status label (without elapsed)
        self._pause_tip_shown = False            # one-time discoverability hint for Pause

        self.setWindowTitle("ElevenLabs Helper")
        self.resize(860, 580)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        # Top bar
        topbar = QHBoxLayout()
        settings_btn = QPushButton("Settings")
        settings_btn.clicked.connect(self._open_settings)
        key_btn = QPushButton("API Key")
        key_btn.clicked.connect(self._open_key)
        history_btn = QPushButton("History…")
        history_btn.setToolTip("Browse & recover past transcripts (re-export for free)")
        history_btn.clicked.connect(self._open_history)
        clear_btn = QPushButton("Clear completed")
        clear_btn.clicked.connect(self._clear_completed)
        self.pause_btn = QPushButton("Pause")
        self.pause_btn.setCheckable(True)
        self.pause_btn.setToolTip("Hold the queue so you can set per-job Options before a job starts")
        self.pause_btn.toggled.connect(self._toggle_pause)
        topbar.addWidget(settings_btn)
        topbar.addWidget(key_btn)
        topbar.addWidget(self.pause_btn)
        topbar.addStretch()
        topbar.addWidget(history_btn)
        topbar.addWidget(clear_btn)
        layout.addLayout(topbar)

        # Privacy disclosure (F1) + storage clarity (U7).
        # Use the theme's default text color (adapts to light/dark, meets contrast); 12px.
        disclosure = QLabel(
            "Audio you add is uploaded to ElevenLabs for transcription; "
            "transcripts are saved to your output folder (shown below)."
        )
        disclosure.setStyleSheet("font-size: 12px;")
        disclosure.setWordWrap(True)
        layout.addWidget(disclosure)

        # No-key gate banner (F2)
        self.key_banner = QFrame()
        self.key_banner.setStyleSheet(
            "QFrame { background: rgba(192,57,43,0.10); border: 1px solid #c0392b; border-radius: 8px; }"
        )
        banner_layout = QHBoxLayout(self.key_banner)
        banner_layout.addWidget(QLabel("Add your ElevenLabs API key to start transcribing."))
        add_key_btn = QPushButton("Add API key…")
        add_key_btn.clicked.connect(self._open_key)
        banner_layout.addStretch()
        banner_layout.addWidget(add_key_btn)
        layout.addWidget(self.key_banner)

        # Drop area
        self.drop = DropArea()
        self.drop.filesDropped.connect(self._add_files)
        self.drop.filesRejected.connect(self._on_files_rejected)
        layout.addWidget(self.drop)

        # Table
        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(_COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        for i in range(1, len(_COLUMNS)):
            header.setSectionResizeMode(i, QHeaderView.ResizeToContents)
        layout.addWidget(self.table)

        # Status bar with permanent output-location indicator (F10)
        self._out_label = QLabel()
        self.statusBar().addPermanentWidget(self._out_label)
        self._update_output_location()

        self.bridge.jobUpdated.connect(self._on_job_updated)

        self._reload_table()
        self.engine.queue.resume_unfinished()
        self._update_key_state()

        # Tick busy rows once a second so long uploads/transcriptions show elapsed time.
        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.timeout.connect(self._tick_elapsed)
        self._elapsed_timer.start(1000)

    def _toggle_pause(self, paused: bool) -> None:
        if paused:
            self.engine.queue.pause()
            self.pause_btn.setText("Resume")
            self.statusBar().showMessage("Queue paused — new jobs wait so you can set Options.", 4000)
        else:
            self.engine.queue.resume()
            self.pause_btn.setText("Pause")

    # --- key gate ------------------------------------------------------------
    def _update_key_state(self) -> None:
        has_key = auth.has_api_key()
        self.key_banner.setVisible(not has_key)
        self.drop.setEnabled(has_key)

    # --- adding work ---------------------------------------------------------
    def _add_files(self, paths: list[str]) -> None:
        added = False
        for path in paths:
            # Oversize gate (warn + acknowledge): size via stat, duration via mutagen.
            info = None
            try:
                info = inspect(path)
            except Exception:
                pass
            warnings = limit_warnings(info) if info else []
            if warnings:
                msg = "\n".join(warnings)
                if info and info.duration_secs is None:
                    msg += "\n(Duration couldn't be read — it may also exceed the 10 h limit.)"
                msg += "\n\nUpload anyway? ElevenLabs may reject it."
                choice = QMessageBox.warning(
                    self, "File may exceed ElevenLabs limits", msg,
                    QMessageBox.Ok | QMessageBox.Cancel, QMessageBox.Cancel,
                )
                if choice != QMessageBox.Ok:
                    continue
            try:
                job = self.engine.add_source(path, acknowledged_oversize=bool(warnings))
            except Exception as exc:  # noqa: BLE001
                QMessageBox.warning(self, "Could not add file", f"{path}\n\n{exc}")
                continue
            self._render_job(job)
            added = True
        # One-time discoverability hint for per-job Options (UX-N1).
        if added and not self._pause_tip_shown and not self.engine.queue.is_paused:
            self._pause_tip_shown = True
            self.statusBar().showMessage(
                "Tip: use Pause to hold the queue and set per-file Options before a job starts.",
                7000,
            )

    def _busy_label(self, job_id: str) -> str:
        base = self._busy_base.get(job_id, "Working")
        elapsed = int(time.monotonic() - self._busy_since.get(job_id, time.monotonic()))
        return f"{base} ({elapsed // 60}:{elapsed % 60:02d})"

    def _tick_elapsed(self) -> None:
        # Refresh just the status text of busy rows (cheap; doesn't rebuild widgets).
        for job_id in list(self._busy_since):
            row = self._rows.get(job_id)
            if row is None:
                continue
            item = self.table.item(row, 1)
            if item is not None:
                item.setText(self._busy_label(job_id))

    def _on_files_rejected(self, count: int) -> None:
        n = f"{count} file{'s' if count != 1 else ''}"
        self.statusBar().showMessage(
            f"Only .mp3 is supported in this version — export an MP3 first. Ignored {n}.", 8000
        )

    # --- table rendering -----------------------------------------------------
    def _on_job_updated(self, job: Job) -> None:
        self._render_job(job)

    def _reload_table(self) -> None:
        """Rebuild the whole table + row index from the store (keeps indices honest)."""
        self.table.setRowCount(0)
        self._rows.clear()
        self._busy_since.clear()
        self._busy_base.clear()
        for job in self.engine.jobs():  # active (non-archived) jobs only
            self._render_job(job)

    def _render_job(self, job: Job) -> None:
        row = self._rows.get(job.id)
        if row is None:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self._rows[job.id] = row

        name_item = QTableWidgetItem(job.source_name)
        name_item.setData(Qt.UserRole, job.id)
        self.table.setItem(row, 0, name_item)

        # Status (F3: human-readable, raw detail in tooltip)
        no_speech = job.status == JobStatus.DONE and job.message == "No speech detected"
        if job.status == JobStatus.FAILED:
            status_text = friendly_error(job.error or job.message)
        elif job.status == JobStatus.DONE:
            status_text = "Completed — no speech detected" if no_speech else "Completed"
        elif job.status in _BUSY_STATUSES:
            base = job.status.value.capitalize()
            if job.size_bytes:
                base += f" {human_size(job.size_bytes)}"
            self._busy_since.setdefault(job.id, time.monotonic())
            self._busy_base[job.id] = base
            status_text = self._busy_label(job.id)
        else:
            status_text = job.status.value.capitalize()
            if job.message:
                status_text = f"{status_text} — {job.message}"
        if job.status not in _BUSY_STATUSES:
            self._busy_since.pop(job.id, None)
            self._busy_base.pop(job.id, None)
        status_item = QTableWidgetItem(status_text)
        if job.error:
            status_item.setToolTip(job.error)
        if job.status == JobStatus.FAILED:
            status_item.setForeground(QColor("#c0392b"))
        elif no_speech:
            # Theme-safe: distinguish via bold + the explicit wording, not a borderline
            # color (meaning is carried by text, so contrast holds in light/dark).
            font = status_item.font()
            font.setBold(True)
            status_item.setFont(font)
        elif job.status == JobStatus.DONE:
            status_item.setForeground(QColor("#27ae60"))
        self.table.setItem(row, 1, status_item)

        # Progress (F11: indeterminate "busy" while uploading/transcribing)
        bar = QProgressBar()
        if job.status in _BUSY_STATUSES:
            bar.setRange(0, 0)
        else:
            bar.setRange(0, 100)
            bar.setValue(int(job.progress * 100))
        self.table.setCellWidget(row, 2, bar)

        facts = "—"
        if job.size_bytes:
            facts = human_size(job.size_bytes)
            facts += (
                f" · {human_duration(job.duration_secs)}"
                if job.duration_secs
                else " · duration unknown"
            )
        self.table.setItem(row, 3, QTableWidgetItem(facts))

        self.table.setCellWidget(row, 4, self._actions(job))

    def _actions(self, job: Job) -> QWidget:
        """One primary action inline + a ⋯ menu for the rest (J5)."""
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(2, 2, 2, 2)
        lay.setSpacing(4)

        primary: tuple[str, object] | None = None
        menu_items: list[tuple[str, object]] = []
        if job.status == JobStatus.QUEUED:
            primary = ("Options", lambda: self._open_job_options(job.id))
            menu_items = [("Cancel", lambda: self._cancel_job(job.id))]
        elif job.status not in TERMINAL_STATUSES:  # active (uploading/transcribing/retrying)
            primary = ("Cancel", lambda: self._cancel_job(job.id))
        elif job.status == JobStatus.DONE:
            # Reveal is the most common action on a finished job (K1); re-export is
            # the rarer recovery path, kept a click away in the menu.
            primary = ("Reveal", lambda: self._reveal(job))
            menu_items = [("Re-export…", lambda: self._reexport(job.id)),
                          ("Remove from list", lambda: self._remove_job(job.id))]
        else:  # FAILED / CANCELED
            primary = ("Retry", lambda: self.engine.queue.retry(job.id))
            menu_items = [("Reveal", lambda: self._reveal(job)),
                          ("Remove from list", lambda: self._remove_job(job.id))]

        if primary:
            btn = QPushButton(primary[0])
            if primary[0] == "Re-export":
                btn.setToolTip("Regenerate deliverables from saved history — no API cost")
            btn.clicked.connect(primary[1])
            lay.addWidget(btn)
        if menu_items:
            lay.addWidget(self._menu_button(menu_items))
        lay.addStretch()
        return w

    def _menu_button(self, items: list[tuple[str, object]]) -> QToolButton:
        btn = QToolButton()
        btn.setText("⋯")
        btn.setToolTip("More actions")
        btn.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu(btn)
        for label, cb in items:
            menu.addAction(label, cb)
        btn.setMenu(menu)
        return btn

    # --- row actions ---------------------------------------------------------
    def _cancel_job(self, job_id: str) -> None:
        # Instant acknowledgment (F5): reflect intent in the status cell immediately,
        # since the engine can only act at step boundaries.
        row = self._rows.get(job_id)
        if row is not None:
            item = self.table.item(row, 1)
            if item is not None:
                item.setText("Canceling…")
        self.engine.queue.cancel(job_id)

    def _reexport(self, job_id: str) -> None:
        job = self.engine.store.get(job_id)
        if job is None:
            return
        if reexport_with_prompt(self, self.engine, job):
            fresh = self.engine.store.get(job_id)
            if fresh:
                self._render_job(fresh)
                row = self._rows.get(job_id)
                if row is not None:
                    self.table.selectRow(row)

    def _open_job_options(self, job_id: str) -> None:
        job = self.engine.store.get(job_id)
        if job is None or job.status != JobStatus.QUEUED:
            return
        dialog = JobOptionsDialog(job, self)
        if dialog.exec():
            # Guard the race: the worker may have dequeued it while the dialog was open.
            fresh = self.engine.store.get(job_id)
            if fresh is None or fresh.status != JobStatus.QUEUED:
                self.statusBar().showMessage("Job already started — options not applied.", 4000)
                return
            self.engine.store.upsert(dialog.job)
            self._render_job(dialog.job)

    def _remove_job(self, job_id: str) -> None:
        # Archive (hide from the list) but KEEP the recovery history — deletion is
        # only possible via the explicit "Delete permanently" in History (J1).
        self.engine.archive(job_id)
        self._reload_table()
        self.statusBar().showMessage("Removed from list — still recoverable in History.", 5000)

    def _clear_completed(self) -> None:
        for job in self.engine.jobs():
            if job.status in TERMINAL_STATUSES:
                self.engine.archive(job.id)
        self._reload_table()
        self.statusBar().showMessage(
            "Cleared from the list. Recover any transcript from History.", 5000
        )

    def _open_history(self) -> None:
        HistoryDialog(self.engine, self).exec()
        self._reload_table()  # a job may have been permanently deleted

    def _reveal(self, job: Job) -> None:
        target = Path(job.output_dir)
        if target.exists():
            subprocess.run(["open", str(target)], check=False)
        else:
            self.statusBar().showMessage("No output folder yet for this job.", 4000)

    # --- dialogs -------------------------------------------------------------
    def _open_settings(self) -> None:
        if SettingsDialog(self.engine.settings, self).exec():
            self._update_output_location()

    def _open_key(self) -> None:
        KeyDialog(self).exec()
        self._update_key_state()

    def _update_output_location(self) -> None:
        root = self.engine.settings.output_root
        where = str(root) if root else "alongside each source file"
        self._out_label.setText(f"Output: {where}")

    def closeEvent(self, event):  # noqa: N802
        self.engine.stop()
        super().closeEvent(event)
