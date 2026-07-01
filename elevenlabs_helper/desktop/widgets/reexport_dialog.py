"""Format picker for re-exporting a completed job from saved history (no API cost)."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QVBoxLayout,
)

from ...engine.config import Deliverable

_LABELS = {
    Deliverable.SRT: "SRT",
    Deliverable.VTT: "VTT",
    Deliverable.DOCX: "DOCX",
    Deliverable.JSON: "JSON",
}


class ReexportDialog(QDialog):
    """Pick which deliverables to regenerate. Prefilled with the job's original choice."""

    def __init__(self, current: list[Deliverable], source_name: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Re-export — {source_name}")
        self.setMinimumWidth(360)
        root = QVBoxLayout(self)
        root.addWidget(QLabel("Regenerate from saved transcript (no API cost):"))

        self.boxes: dict[Deliverable, QCheckBox] = {}
        for d in (Deliverable.SRT, Deliverable.VTT, Deliverable.DOCX, Deliverable.JSON):
            box = QCheckBox(_LABELS[d])
            box.setChecked(d in current)
            self.boxes[d] = box
            root.addWidget(box)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Re-export")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def selected(self) -> list[Deliverable]:
        return [d for d, b in self.boxes.items() if b.isChecked()]
