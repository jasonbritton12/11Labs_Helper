"""Settings dialog: output location, deliverables, transcription toggles."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...engine.config import Deliverable, EngineSettings


class SettingsDialog(QDialog):
    def __init__(self, settings: EngineSettings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("Settings")
        self.setMinimumWidth(460)
        root = QVBoxLayout(self)
        form = QFormLayout()

        # Output folder
        self.out_field = QLineEdit(str(settings.output_root) if settings.output_root else "")
        self.out_field.setPlaceholderText("(alongside each source file)")
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._pick_folder)
        out_row = QWidget()
        out_layout = QHBoxLayout(out_row)
        out_layout.setContentsMargins(0, 0, 0, 0)
        out_layout.addWidget(self.out_field)
        out_layout.addWidget(browse)
        form.addRow("Output folder:", out_row)
        root.addLayout(form)

        # Deliverables
        root.addWidget(QLabel("Deliverables:"))
        self.deliv_boxes: dict[Deliverable, QCheckBox] = {}
        for d in (Deliverable.SRT, Deliverable.VTT, Deliverable.DOCX):
            box = QCheckBox(d.value.upper())
            box.setChecked(d in settings.deliverables)
            self.deliv_boxes[d] = box
            root.addWidget(box)

        # Transcription toggles
        root.addWidget(QLabel("Transcription:"))
        self.diarize = QCheckBox("Speaker diarization")
        self.diarize.setChecked(settings.transcription.diarize)
        self.tag_events = QCheckBox("Audio-event tagging")
        self.tag_events.setChecked(settings.transcription.tag_audio_events)
        self.auto_lang = QCheckBox("Auto-detect language")
        self.auto_lang.setChecked(settings.transcription.language_code is None)
        self.keep_raw_json = QCheckBox("Keep raw JSON (full word-level data) on disk")
        self.keep_raw_json.setChecked(settings.keep_raw_json)
        for w in (self.diarize, self.tag_events, self.auto_lang, self.keep_raw_json):
            root.addWidget(w)

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
        self.settings.keep_raw_json = self.keep_raw_json.isChecked()
        self.settings.save()
        self.accept()
