"""Speaker QC: review/rename/reassign diarized speakers before dubbing upload.

Fixing speaker assignment here — instead of inside ElevenLabs Dubbing Studio —
means the exported Manual-Dub CSV starts the Studio project with correct clips
and speakers (and regenerations there cost credits; this pass is free).

Edits are stored as an overlay (see ``engine.edits``); the canonical transcript
is never modified, and every export format reflects the edits.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from ...engine.edits import SpeakerEdits
from ...engine.exporters.canonical import Transcript
from ...engine.jobs.models import Job
from ...engine.service import Engine


def _ts(seconds: float) -> str:
    ms = int(round(max(seconds, 0) * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


class SpeakerQCDialog(QDialog):
    """Table of cues with a speaker dropdown per row + per-speaker rename fields."""

    def __init__(self, engine: Engine, job: Job, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.job = job
        self.setWindowTitle(f"Speaker QC — {job.source_name}")
        self.resize(760, 560)

        # Raw (unedited) transcript is the baseline overrides are computed against.
        self._raw: Transcript = engine.get_transcript(job.id, with_edits=False)
        self._edits: SpeakerEdits = engine.get_speaker_edits(job.id)
        self._speakers = sorted(
            {c.speaker_id for c in self._raw.cues if c.speaker_id and not c.is_audio_event}
        )

        root = QVBoxLayout(self)
        root.addWidget(QLabel(
            "Review speaker assignment before uploading to Dubbing Studio. "
            "Changes apply to all exports (SRT/VTT/DOCX and the Dubbing CSV)."
        ))

        # --- rename fields (one per detected speaker) -------------------------
        self._name_fields: dict[str, QLineEdit] = {}
        if self._speakers:
            grid = QGridLayout()
            for i, sid in enumerate(self._speakers):
                default = self._default_label(sid)
                field = QLineEdit(self._edits.speaker_names.get(sid, default))
                field.setPlaceholderText(default)
                field.textChanged.connect(self._refresh_combo_labels)
                self._name_fields[sid] = field
                grid.addWidget(QLabel(default + ":"), i // 2, (i % 2) * 2)
                grid.addWidget(field, i // 2, (i % 2) * 2 + 1)
            root.addLayout(grid)

        # --- cue table --------------------------------------------------------
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["#", "Start", "End", "Speaker", "Text"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(4, QHeaderView.Stretch)
        for i in range(4):
            header.setSectionResizeMode(i, QHeaderView.ResizeToContents)

        self._combos: dict[int, QComboBox] = {}  # cue index -> combo
        for cue in self._raw.cues:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(str(cue.index)))
            self.table.setItem(row, 1, QTableWidgetItem(_ts(cue.start)))
            self.table.setItem(row, 2, QTableWidgetItem(_ts(cue.end)))
            if cue.is_audio_event:
                self.table.setItem(row, 3, QTableWidgetItem("—"))
            else:
                combo = QComboBox()
                for sid in self._speakers:
                    combo.addItem(self._display_name(sid), sid)
                effective = self._edits.cue_overrides.get(cue.index, cue.speaker_id)
                if effective in self._speakers:
                    combo.setCurrentIndex(self._speakers.index(effective))
                self._combos[cue.index] = combo
                self.table.setCellWidget(row, 3, combo)
            self.table.setItem(row, 4, QTableWidgetItem(cue.text))
        root.addWidget(self.table)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    # --- helpers -------------------------------------------------------------
    def _default_label(self, sid: str) -> str:
        return Transcript().speaker_label(sid)  # "Speaker N" without user names

    def _display_name(self, sid: str) -> str:
        field = self._name_fields.get(sid)
        text = field.text().strip() if field else ""
        return text or self._default_label(sid)

    def _refresh_combo_labels(self) -> None:
        for combo in self._combos.values():
            for i in range(combo.count()):
                combo.setItemText(i, self._display_name(combo.itemData(i)))

    def _save(self) -> None:
        names = {
            sid: field.text().strip()
            for sid, field in self._name_fields.items()
            if field.text().strip() and field.text().strip() != self._default_label(sid)
        }
        overrides: dict[int, str] = {}
        for cue in self._raw.cues:
            combo = self._combos.get(cue.index)
            if combo is None:
                continue
            chosen = combo.currentData()
            if chosen and chosen != cue.speaker_id:
                overrides[cue.index] = chosen
        self.engine.save_speaker_edits(
            self.job.id, SpeakerEdits(speaker_names=names, cue_overrides=overrides)
        )
        self.accept()
