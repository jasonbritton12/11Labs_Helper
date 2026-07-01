"""Settings dialog — grouped: Deliverables, Transcription, Storage & history."""

from __future__ import annotations

import subprocess
from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...engine.config import Deliverable, EngineSettings
from ...engine.history import history_dir

_DELIV_LABELS = {
    Deliverable.SRT: "SRT",
    Deliverable.VTT: "VTT",
    Deliverable.DOCX: "DOCX",
    Deliverable.JSON: "JSON",
}


class SettingsDialog(QDialog):
    def __init__(self, settings: EngineSettings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("Settings")
        self.setMinimumWidth(480)
        root = QVBoxLayout(self)

        # --- Deliverables --------------------------------------------------
        deliv_group = QGroupBox("Deliverables (saved to your output folder)")
        deliv_layout = QVBoxLayout(deliv_group)
        self.deliv_boxes: dict[Deliverable, QCheckBox] = {}
        for d in (Deliverable.SRT, Deliverable.VTT, Deliverable.DOCX, Deliverable.JSON):
            box = QCheckBox(_DELIV_LABELS[d])
            box.setChecked(d in settings.deliverables)
            self.deliv_boxes[d] = box
            deliv_layout.addWidget(box)
        root.addWidget(deliv_group)

        # --- Transcription -------------------------------------------------
        stt_group = QGroupBox("Transcription")
        stt_layout = QVBoxLayout(stt_group)
        self.diarize = QCheckBox("Speaker diarization")
        self.diarize.setChecked(settings.transcription.diarize)
        self.tag_events = QCheckBox("Audio-event tagging")
        self.tag_events.setChecked(settings.transcription.tag_audio_events)
        self.auto_lang = QCheckBox("Auto-detect language")
        self.auto_lang.setChecked(settings.transcription.language_code is None)
        for w in (self.diarize, self.tag_events, self.auto_lang):
            stt_layout.addWidget(w)
        root.addWidget(stt_group)

        # --- Storage & history --------------------------------------------
        store_group = QGroupBox("Storage & history")
        store_layout = QVBoxLayout(store_group)

        self.out_field = QLineEdit(str(settings.output_root) if settings.output_root else "")
        self.out_field.setPlaceholderText("(alongside each source file)")
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._pick_folder)
        out_row = QWidget()
        out_layout = QHBoxLayout(out_row)
        out_layout.setContentsMargins(0, 0, 0, 0)
        out_layout.addWidget(QLabel("Output folder:"))
        out_layout.addWidget(self.out_field)
        out_layout.addWidget(browse)
        store_layout.addWidget(out_row)

        self.keep_history = QCheckBox("Keep transcript history (enables free re-export)")
        self.keep_history.setChecked(settings.keep_history_json)
        store_layout.addWidget(self.keep_history)

        note = QLabel(
            "A copy of each transcript's JSON is kept privately here — separate from "
            "your output files — so you can re-export deliverables without re-transcribing. "
            "Turning this off stops new copies (existing ones are kept)."
        )
        note.setWordWrap(True)
        note.setStyleSheet("font-size: 11px;")
        store_layout.addWidget(note)

        reveal_hist = QPushButton("Reveal history folder")
        reveal_hist.clicked.connect(lambda: subprocess.run(["open", str(history_dir())], check=False))
        store_layout.addWidget(reveal_hist)
        root.addWidget(store_group)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _pick_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Choose output folder")
        if folder:
            self.out_field.setText(folder)

    def _save(self) -> None:
        text = self.out_field.text().strip()
        self.settings.output_root = Path(text) if text else None
        self.settings.deliverables = [d for d, b in self.deliv_boxes.items() if b.isChecked()]
        self.settings.transcription.diarize = self.diarize.isChecked()
        self.settings.transcription.tag_audio_events = self.tag_events.isChecked()
        if self.auto_lang.isChecked():
            self.settings.transcription.language_code = None
        self.settings.keep_history_json = self.keep_history.isChecked()
        self.settings.save()
        self.accept()
