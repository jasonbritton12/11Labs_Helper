"""Render a Transcript to SRT.

Speaker changes are marked with a leading ``- `` (no "Speaker N:" labels);
audio-event cues are rendered bare.
"""

from __future__ import annotations

from .canonical import Transcript, caption_lines


def _ts(seconds: float) -> str:
    if seconds < 0:
        seconds = 0
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def render(transcript: Transcript) -> str:
    lines = caption_lines(transcript)
    blocks: list[str] = []
    for i, (cue, text) in enumerate(zip(transcript.cues, lines), start=1):
        blocks.append(f"{i}\n{_ts(cue.start)} --> {_ts(cue.end)}\n{text}\n")
    return "\n".join(blocks)
