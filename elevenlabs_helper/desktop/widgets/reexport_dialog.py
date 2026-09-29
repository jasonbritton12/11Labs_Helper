"""Format + destination picker for re-exporting a job from saved history (no API cost)."""

from __future__ import annotations

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
)

from ...engine.config import DELIVERABLE_LABELS, Deliverable
from ...engine.captions import CaptionExportOptions, CaptionTimingMode


class ReexportDialog(QDialog):
    """Pick which deliverables to regenerate and where. Prefilled with the job's choice."""

    def __init__(self, current: list[Deliverable], source_name: str, default_out: str,
                 parent=None, *, caption_options: CaptionExportOptions | None = None,
                 readable_default: bool | None = None):
        super().__init__(parent)
        # ``readable_default`` remains accepted while engine re-export still
        # exposes its legacy boolean API. The UI itself has one timing enum.
        if caption_options is None:
            caption_options = CaptionExportOptions(
                timing_mode=(
                    CaptionTimingMode.HOUSE
                    if readable_default
                    else CaptionTimingMode.SOURCE
                )
            )
        self._caption_options_seed = caption_options.model_copy(deep=True)
        self.setWindowTitle(f"Re-export — {source_name}")
        self.setMinimumWidth(420)
        root = QVBoxLayout(self)
        root.addWidget(QLabel("Regenerate from saved transcript (no API cost):"))

        self.boxes: dict[Deliverable, QCheckBox] = {}
        for d in (Deliverable.SRT, Deliverable.VTT, Deliverable.DOCX, Deliverable.JSON,
                  Deliverable.DUB_CSV):
            box = QCheckBox(DELIVERABLE_LABELS[d])
            box.setChecked(d in current)
            self.boxes[d] = box
            root.addWidget(box)
        self.boxes[Deliverable.DUB_CSV].setToolTip(
            "Speaker/timing/text script for ElevenLabs Dubbing Studio's Manual Dub upload"
        )

        caption_group = QGroupBox("Caption files (SRT/VTT)")
        caption_layout = QVBoxLayout(caption_group)
        self.caption_timing_box = QCheckBox("Keep ElevenLabs timing (SRT/VTT)")
        self.caption_timing_box.setToolTip(
            "Keep cue boundaries derived from ElevenLabs word timestamps. Line breaks "
            "and caption checks still apply. Turn this off to author timing using the "
            "608/708/Web house rules. Dubbing CSV always keeps source timing."
        )
        self.caption_timing_box.setChecked(
            self._caption_options_seed.timing_mode == CaptionTimingMode.SOURCE
        )
        # Compatibility alias for callers that still invoke readable_subtitles().
        self.readable_box = self.caption_timing_box
        self.keep_elevenlabs_timing = self.caption_timing_box
        caption_layout.addWidget(self.caption_timing_box)
        caption_help = QLabel(self.caption_timing_box.toolTip())
        caption_help.setWordWrap(True)
        caption_help.setStyleSheet("font-size: 11px;")
        caption_layout.addWidget(caption_help)
        root.addWidget(caption_group)
        for deliverable in (Deliverable.SRT, Deliverable.VTT):
            self.boxes[deliverable].toggled.connect(self._sync_caption_timing_enabled)
        self._sync_caption_timing_enabled()

        root.addWidget(QLabel("Save to:"))
        dest_row = QHBoxLayout()
        self.dest = QLineEdit(default_out)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._pick_folder)
        dest_row.addWidget(self.dest)
        dest_row.addWidget(browse)
        root.addLayout(dest_row)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Re-export")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _pick_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Choose destination folder", self.dest.text())
        if folder:
            self.dest.setText(folder)

    def selected(self) -> list[Deliverable]:
        return [d for d, b in self.boxes.items() if b.isChecked()]

    def _sync_caption_timing_enabled(self) -> None:
        self.caption_timing_box.setEnabled(
            any(
                self.boxes[deliverable].isChecked()
                for deliverable in (Deliverable.SRT, Deliverable.VTT)
            )
        )

    def caption_options(self) -> CaptionExportOptions:
        return self._caption_options_seed.model_copy(
            update={
                "timing_mode": (
                    CaptionTimingMode.SOURCE
                    if self.caption_timing_box.isChecked()
                    else CaptionTimingMode.HOUSE
                )
            }
        )

    def readable_subtitles(self) -> bool:
        """Deprecated boolean adapter for the old re-export service API."""
        return self.caption_options().timing_mode == CaptionTimingMode.HOUSE

    def out_dir(self) -> str:
        return self.dest.text().strip()
