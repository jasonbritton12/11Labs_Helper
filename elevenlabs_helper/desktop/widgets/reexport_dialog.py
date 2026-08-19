"""Format + destination picker for re-exporting a job from saved history (no API cost)."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from ...engine.config import DELIVERABLE_LABELS, Deliverable


class ReexportDialog(QDialog):
    """Pick which deliverables to regenerate and where. Prefilled with the job's choice."""

    def __init__(self, current: list[Deliverable], source_name: str, default_out: str,
                 parent=None, *, readable_default: bool = False):
        super().__init__(parent)
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

        self.readable_box = QCheckBox("Readable subtitle timing (SRT/VTT)")
        self.readable_box.setToolTip(
            "Relax subtitle display timing for reading comfort (min duration, reading-speed cap).\n"
            "The Dubbing CSV always keeps exact waveform timing."
        )
        self.readable_box.setChecked(readable_default)
        root.addWidget(self.readable_box)

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

    def readable_subtitles(self) -> bool:
        return self.readable_box.isChecked()

    def out_dir(self) -> str:
        return self.dest.text().strip()
