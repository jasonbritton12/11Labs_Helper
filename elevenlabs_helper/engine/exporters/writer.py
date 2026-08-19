"""Write the user-selected deliverables to an output folder.

The canonical transcript JSON is NOT written here by default — it's kept in the
app history space (see ``engine.history``). JSON only lands in the output folder
when the user explicitly selects it as a deliverable (an extra user-facing copy).
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from ..config import Deliverable
from ..elevenlabs.models import TranscriptionResult
from . import docx as docx_exporter
from . import dub_csv as dub_csv_exporter
from . import srt as srt_exporter
from . import vtt as vtt_exporter
from .canonical import apply_edits, build_transcript
from .readability import retime

if TYPE_CHECKING:
    from ..edits import SpeakerEdits

_EXT = {
    Deliverable.SRT: "srt",
    Deliverable.VTT: "vtt",
    Deliverable.DOCX: "docx",
    Deliverable.JSON: "json",
    Deliverable.DUB_CSV: "csv",
}


def deliverable_paths(out_dir, stem: str, deliverables) -> list[Path]:
    """Target file paths for the given deliverables (without writing) — for overwrite checks."""
    out = Path(out_dir)
    return [out / f"{stem}.{_EXT[d]}" for d in deliverables if d in _EXT]


def write_deliverables(
    result: TranscriptionResult,
    out_dir: str | Path,
    stem: str,
    deliverables: list[Deliverable],
    *,
    edits: "SpeakerEdits | None" = None,
    readable_subtitles: bool = False,
) -> dict[str, Path]:
    """Render ``result`` to ``out_dir/<stem>.<ext>`` for each requested deliverable.

    ``edits`` applies user speaker renames/reassignments (see ``engine.edits``).
    ``readable_subtitles`` re-times SRT/VTT for reading comfort; the Dubbing CSV
    always keeps waveform-aligned timing regardless.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    transcript = build_transcript(result)
    if edits is not None:
        transcript = apply_edits(transcript, edits)
    subtitle_transcript = retime(transcript) if readable_subtitles else transcript
    artifacts: dict[str, Path] = {}

    if Deliverable.SRT in deliverables:
        p = out_dir / f"{stem}.srt"
        p.write_text(srt_exporter.render(subtitle_transcript))
        artifacts["srt"] = p
    if Deliverable.VTT in deliverables:
        p = out_dir / f"{stem}.vtt"
        p.write_text(vtt_exporter.render(subtitle_transcript))
        artifacts["vtt"] = p
    if Deliverable.DOCX in deliverables:
        p = out_dir / f"{stem}.docx"
        docx_exporter.write(transcript, p)
        artifacts["docx"] = p
    if Deliverable.JSON in deliverables:  # optional user-facing copy
        p = out_dir / f"{stem}.json"
        p.write_text(result.model_dump_json(indent=2))
        artifacts["json"] = p
    if Deliverable.DUB_CSV in deliverables:  # waveform-aligned by design
        p = out_dir / f"{stem}.csv"
        p.write_text(dub_csv_exporter.render(transcript))
        artifacts["dub_csv"] = p

    return artifacts
