"""Render a Transcript to an ElevenLabs Dubbing Studio "Manual Dub" CSV.

Columns (fixed by ElevenLabs): speaker,start_time,end_time,transcription,translation
Timecodes are plain seconds with millisecond precision — one of the three forms
Manual Dub accepts, chosen because the HH:MM:SS,mmm form contains commas and
would force CSV quoting that a strict parser may mishandle.

Uploading this CSV alongside the video when creating a Dubbing Studio project
locks in clip boundaries and speaker assignment up front, so no in-Studio
reassignment pass is needed. Timing is the waveform-aligned cue timing — never
the readability-retimed subtitle variant (see ``readability.py``).

The ``translation`` column is left empty for now; the Studio fills it, or a
future translation pass (Phase 2) can populate it before upload.
"""

from __future__ import annotations

import csv
import io

from .canonical import Transcript

HEADER = ["speaker", "start_time", "end_time", "transcription", "translation"]


def _ts(seconds: float) -> str:
    return f"{max(seconds, 0):.3f}"


def render(transcript: Transcript) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(HEADER)
    for cue in transcript.cues:
        if cue.is_audio_event:
            continue  # only spoken dialogue belongs in a dubbing script
        writer.writerow(
            [
                transcript.speaker_label(cue.speaker_id),
                _ts(cue.start),
                _ts(cue.end),
                cue.text,
                "",
            ]
        )
    return buf.getvalue()
