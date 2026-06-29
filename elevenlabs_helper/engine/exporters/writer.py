"""Write the selected deliverables (and the always-on raw JSON) to disk."""

from __future__ import annotations

from pathlib import Path

from ..config import Deliverable
from ..elevenlabs.models import TranscriptionResult
from . import docx as docx_exporter
from . import srt as srt_exporter
from . import vtt as vtt_exporter
from .canonical import build_transcript


def write_deliverables(
    result: TranscriptionResult,
    out_dir: str | Path,
    stem: str,
    deliverables: list[Deliverable],
    *,
    keep_raw_json: bool = True,
) -> dict[str, Path]:
    """Render ``result`` to ``out_dir/<stem>.<ext>`` for each requested deliverable.

    Writes ``<stem>.raw.json`` (full word-level data) unless ``keep_raw_json`` is
    False — a data-at-rest control for sensitive transcripts.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    transcript = build_transcript(result)
    artifacts: dict[str, Path] = {}

    # Canonical raw JSON — retained unless the user opts out.
    if keep_raw_json:
        raw_path = out_dir / f"{stem}.raw.json"
        raw_path.write_text(result.model_dump_json(indent=2))
        artifacts["json"] = raw_path

    if Deliverable.SRT in deliverables:
        p = out_dir / f"{stem}.srt"
        p.write_text(srt_exporter.render(transcript))
        artifacts["srt"] = p
    if Deliverable.VTT in deliverables:
        p = out_dir / f"{stem}.vtt"
        p.write_text(vtt_exporter.render(transcript))
        artifacts["vtt"] = p
    if Deliverable.DOCX in deliverables:
        p = out_dir / f"{stem}.docx"
        docx_exporter.write(transcript, p)
        artifacts["docx"] = p

    return artifacts
