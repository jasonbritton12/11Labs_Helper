"""Per-job options — override defaults for a single queued job (UX F6)."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
)

from ...engine.config import Deliverable
from ...engine.jobs.models import Job


class JobOptionsDialog(QDialog):
    """Edits a single Job's params in place. Only meaningful while the job is queued."""

    def __init__(self, job: Job, parent=None):
        super().__init__(parent)
        self.job = job
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
        for d in (Deliverable.SRT, Deliverable.VTT, Deliverable.DOCX):
            box = QCheckBox(d.value.upper())
            box.setChecked(d in job.deliverables)
            self.deliv_boxes[d] = box
            root.addWidget(box)

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

    def _save(self) -> None:
        if self.auto_lang.isChecked():
            self.job.params.language_code = None
        else:
            self.job.params.language_code = self.lang_field.text().strip() or None
        self.job.deliverables = [d for d, b in self.deliv_boxes.items() if b.isChecked()]
        self.job.params.diarize = self.diarize.isChecked()
        self.job.params.tag_audio_events = self.tag_events.isChecked()
        self.accept()
