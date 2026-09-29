"""Per-job options — override defaults for a single queued job (UX F6)."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QVBoxLayout,
)

from ...engine.captions import CaptionExportOptions, CaptionTimingMode
from ...engine.config import DELIVERABLE_LABELS, Deliverable
from ...engine.jobs.models import Job


class JobOptionsDialog(QDialog):
    """Edits a single Job's params in place. Only meaningful while the job is queued."""

    def __init__(self, job: Job, parent=None):
        super().__init__(parent)
        self.job = job
        self._caption_options_seed = (
            job.staged_caption_options.model_copy(deep=True)
            if job.staged_caption_options is not None
            else CaptionExportOptions()
        )
        self.setWindowTitle(f"Options — {job.source_name}")
        self.setMinimumWidth(420)
        root = QVBoxLayout(self)
        form = QFormLayout()

        self.auto_lang = QCheckBox("Auto-detect")
        self.auto_lang.setChecked(job.params.language_code is None)
        self.lang_field = QLineEdit(job.params.language_code or "")
        self.lang_field.setPlaceholderText("e.g. eng, spa")
        self.lang_field.setEnabled(job.params.language_code is not None)
        self.auto_lang.toggled.connect(lambda on: self.lang_field.setEnabled(not on))
        form.addRow("Language:", self.auto_lang)
        form.addRow("", self.lang_field)
        root.addLayout(form)

        root.addWidget(QLabel("Deliverables:"))
        self.deliv_boxes: dict[Deliverable, QCheckBox] = {}
        for d in (
            Deliverable.SRT,
            Deliverable.VTT,
            Deliverable.DOCX,
            Deliverable.JSON,
            Deliverable.DUB_CSV,
        ):
            box = QCheckBox(DELIVERABLE_LABELS[d])
            box.setChecked(d in job.deliverables)
            self.deliv_boxes[d] = box
            root.addWidget(box)

        caption_group = QGroupBox("Caption files (SRT/VTT)")
        caption_layout = QVBoxLayout(caption_group)
        self.caption_timing_box = QCheckBox("Keep ElevenLabs timing (SRT/VTT)")
        self.caption_timing_box.setChecked(
            self._caption_options_seed.timing_mode == CaptionTimingMode.SOURCE
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

        self.diarize = QCheckBox("Speaker diarization")
        self.diarize.setChecked(job.params.diarize)
        self.tag_events = QCheckBox("Audio-event tagging")
        self.tag_events.setChecked(job.params.tag_audio_events)
        root.addWidget(self.diarize)
        root.addWidget(self.tag_events)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _sync_caption_timing_enabled(self) -> None:
        self.caption_timing_box.setEnabled(
            any(
                self.deliv_boxes[deliverable].isChecked()
                for deliverable in (Deliverable.SRT, Deliverable.VTT)
            )
        )

    def _save(self) -> None:
        if self.auto_lang.isChecked():
            self.job.params.language_code = None
        else:
            self.job.params.language_code = self.lang_field.text().strip() or None
        self.job.deliverables = [d for d, b in self.deliv_boxes.items() if b.isChecked()]
        self.job.params.diarize = self.diarize.isChecked()
        self.job.params.tag_audio_events = self.tag_events.isChecked()
        self.job.staged_caption_options = self._caption_options_seed.model_copy(
            update={
                "timing_mode": (
                    CaptionTimingMode.SOURCE
                    if self.caption_timing_box.isChecked()
                    else CaptionTimingMode.HOUSE
                )
            }
        )
        self.accept()
