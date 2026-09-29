"""Settings dialog — grouped: Deliverables, Transcription, Storage & history."""

from __future__ import annotations

import copy
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
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ...engine.captions import CaptionTimingMode
from ...engine.config import DELIVERABLE_LABELS, Deliverable, EngineSettings
from ...engine.history import history_dir


class SettingsDialog(QDialog):
    def __init__(self, settings: EngineSettings, parent=None):
        super().__init__(parent)
        # Keep the instance shared by Engine and JobQueue untouched until a full,
        # validated candidate has been persisted successfully.
        self.settings = settings
        self._candidate = settings.model_copy(deep=True)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(480)
        root = QVBoxLayout(self)

        # --- Deliverables --------------------------------------------------
        deliv_group = QGroupBox("Deliverables (saved to your output folder)")
        deliv_layout = QVBoxLayout(deliv_group)
        self.deliv_boxes: dict[Deliverable, QCheckBox] = {}
        for d in (
            Deliverable.SRT,
            Deliverable.VTT,
            Deliverable.DOCX,
            Deliverable.JSON,
            Deliverable.DUB_CSV,
        ):
            box = QCheckBox(DELIVERABLE_LABELS[d])
            box.setChecked(d in self._candidate.deliverables)
            self.deliv_boxes[d] = box
            deliv_layout.addWidget(box)
        root.addWidget(deliv_group)

        # --- Caption files -------------------------------------------------
        caption_group = QGroupBox("Caption files (SRT/VTT)")
        caption_layout = QVBoxLayout(caption_group)
        self.caption_timing_box = QCheckBox("Keep ElevenLabs timing (SRT/VTT)")
        self.caption_timing_box.setChecked(
            self._candidate.caption_timing_mode == CaptionTimingMode.SOURCE
        )
        self.caption_timing_box.setToolTip(
            "Keep cue boundaries derived from ElevenLabs word timestamps. Line breaks "
            "and caption checks still apply. Turn this off to author timing using the "
            "608/708/Web house rules. Dubbing CSV always keeps source timing."
        )
        self.keep_elevenlabs_timing = self.caption_timing_box
        caption_layout.addWidget(self.caption_timing_box)
        caption_help = QLabel(self.caption_timing_box.toolTip())
        caption_help.setWordWrap(True)
        caption_help.setStyleSheet("font-size: 11px;")
        caption_layout.addWidget(caption_help)
        root.addWidget(caption_group)
        for deliverable in (Deliverable.SRT, Deliverable.VTT):
            self.deliv_boxes[deliverable].toggled.connect(self._sync_caption_timing_enabled)
        self._sync_caption_timing_enabled()

        # --- Transcription -------------------------------------------------
        stt_group = QGroupBox("Transcription")
        stt_layout = QVBoxLayout(stt_group)
        self.diarize = QCheckBox("Speaker diarization")
        self.diarize.setChecked(self._candidate.transcription.diarize)
        self.tag_events = QCheckBox("Audio-event tagging")
        self.tag_events.setChecked(self._candidate.transcription.tag_audio_events)
        self.auto_lang = QCheckBox("Auto-detect language")
        self.auto_lang.setChecked(self._candidate.transcription.language_code is None)
        for w in (self.diarize, self.tag_events, self.auto_lang):
            stt_layout.addWidget(w)
        root.addWidget(stt_group)

        # --- Storage & history --------------------------------------------
        store_group = QGroupBox("Storage & history")
        store_layout = QVBoxLayout(store_group)

        self.out_field = QLineEdit(
            str(self._candidate.output_root) if self._candidate.output_root else ""
        )
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
        self.keep_history.setChecked(self._candidate.keep_history_json)
        store_layout.addWidget(self.keep_history)

        expiry_row = QWidget()
        expiry_layout = QHBoxLayout(expiry_row)
        expiry_layout.setContentsMargins(0, 0, 0, 0)
        expiry_layout.addWidget(QLabel("Auto-delete history after"))
        self.retention = QSpinBox()
        self.retention.setRange(0, 3650)
        self.retention.setSpecialValueText("never")  # shown when value == 0
        self.retention.setSuffix(" days")
        self.retention.setValue(self._candidate.history_retention_days)
        expiry_layout.addWidget(self.retention)
        expiry_layout.addStretch()
        store_layout.addWidget(expiry_row)

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

    def _sync_caption_timing_enabled(self) -> None:
        """Caption timing only applies when the selected output includes SRT or VTT."""
        enabled = any(
            self.deliv_boxes[deliverable].isChecked()
            for deliverable in (Deliverable.SRT, Deliverable.VTT)
        )
        # Disabling deliberately leaves the selected value intact for a later
        # SRT/VTT selection.
        self.caption_timing_box.setEnabled(enabled)

    def _update_candidate(self) -> None:
        text = self.out_field.text().strip()
        self._candidate.output_root = Path(text) if text else None
        self._candidate.deliverables = [
            deliverable
            for deliverable, box in self.deliv_boxes.items()
            if box.isChecked()
        ]
        self._candidate.transcription.diarize = self.diarize.isChecked()
        self._candidate.transcription.tag_audio_events = self.tag_events.isChecked()
        if self.auto_lang.isChecked():
            self._candidate.transcription.language_code = None
        self._candidate.keep_history_json = self.keep_history.isChecked()
        self._candidate.history_retention_days = self.retention.value()
        self._candidate.caption_timing_mode = (
            CaptionTimingMode.SOURCE
            if self.caption_timing_box.isChecked()
            else CaptionTimingMode.HOUSE
        )

    def _commit_candidate(self) -> None:
        """Copy public values in place so Engine and JobQueue retain their reference."""
        for field_name in type(self.settings).model_fields:
            setattr(
                self.settings,
                field_name,
                copy.deepcopy(getattr(self._candidate, field_name)),
            )

    def _save(self) -> None:
        self._update_candidate()
        try:
            self._candidate.save()
        except Exception as exc:  # noqa: BLE001 - surface the persistence failure verbatim.
            QMessageBox.warning(self, "Could not save settings", str(exc))
            return
        self._commit_candidate()
        self.accept()
