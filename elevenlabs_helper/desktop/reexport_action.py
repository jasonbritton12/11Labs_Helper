"""Shared re-export flow: format + destination picker (J2/K5) + overwrite guard (J4) + feedback (J6)."""

from __future__ import annotations

import subprocess
from pathlib import Path

from PySide6.QtWidgets import QMessageBox

from ..engine.exporters.writer import deliverable_paths
from ..engine.jobs.models import Job
from .widgets.reexport_dialog import ReexportDialog


def reexport_with_prompt(parent, engine, job: Job) -> dict | None:
    """Prompt for formats + destination, guard overwrites, re-export from history, confirm.

    Returns the artifacts dict on success, or None if canceled/failed.
    """
    dialog = ReexportDialog(
        list(job.deliverables), job.source_name, job.output_dir, parent,
        readable_default=engine.settings.readable_subtitles,
    )
    if not dialog.exec():
        return None
    formats = dialog.selected()
    if not formats:
        QMessageBox.information(parent, "Nothing selected", "Choose at least one format.")
        return None
    out_dir = dialog.out_dir() or job.output_dir

    # Overwrite guard (J4): warn if any target file already exists.
    stem = Path(job.source_path).stem
    existing = [p for p in deliverable_paths(out_dir, stem, formats) if p.exists()]
    if existing:
        names = ", ".join(p.name for p in existing)
        if QMessageBox.question(
            parent, "Overwrite existing files?",
            f"These files already exist and will be replaced:\n{names}\n\nContinue?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        ) != QMessageBox.Yes:
            return None

    try:
        artifacts = engine.reexport(
            job.id, deliverables=formats, out_dir=out_dir,
            readable_subtitles=dialog.readable_subtitles(),
        )
    except Exception as exc:  # noqa: BLE001
        QMessageBox.warning(parent, "Re-export failed", str(exc))
        return None

    # Feedback (J6): confirm with a Reveal affordance.
    choice = QMessageBox.information(
        parent, "Re-exported",
        f"Wrote {len(artifacts)} file(s) to:\n{out_dir}",
        QMessageBox.Open | QMessageBox.Ok, QMessageBox.Ok,
    )
    if choice == QMessageBox.Open and Path(out_dir).exists():
        subprocess.run(["open", str(out_dir)], check=False)
    return artifacts
