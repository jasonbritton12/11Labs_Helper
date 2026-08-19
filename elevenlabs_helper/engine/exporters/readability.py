"""Re-time subtitle cues for reading comfort.

Scribe timestamps are waveform-aligned: a cue disappears the instant speech
stops, which can be too fast to read. This pure transform relaxes display
timing for SRT/VTT without touching the canonical transcript, so dubbing
exports (which must stay waveform-aligned) are unaffected.

Rules, in order:
1. Merge a too-short cue into the previous one when they share a speaker and
   the merge stays within normal cue size limits.
2. Extend each cue's end into the following silence until it meets a minimum
   duration and a maximum characters-per-second, leaving a small gap before
   the next cue. Starts are never moved (they anchor to speech onset).
"""

from __future__ import annotations

from dataclasses import replace

from .canonical import Cue, Transcript

# Conventional subtitle-readability defaults (Netflix-style guidance).
MIN_DURATION_SECS = 1.0    # never show a cue shorter than this
MAX_CHARS_PER_SEC = 17.0   # reading speed cap
MIN_GAP_SECS = 0.083       # ~2 frames of air between consecutive cues
MERGE_BELOW_SECS = 0.833   # cues shorter than this try to merge into the previous
_MERGE_MAX_CHARS = 84      # keep merged cues within the canonical cue-size limit
_MERGE_MAX_SECS = 7.0
_MAX_EXTENSION_SECS = 5.0  # never hold a cue absurdly long on a trailing silence


def _required_duration(text: str) -> float:
    return max(MIN_DURATION_SECS, len(text) / MAX_CHARS_PER_SEC)


def retime(transcript: Transcript) -> Transcript:
    """Return a new Transcript with readability-adjusted cue timing."""
    merged: list[Cue] = []
    for cue in transcript.cues:
        prev = merged[-1] if merged else None
        can_merge = (
            prev is not None
            and not cue.is_audio_event
            and not prev.is_audio_event
            and cue.speaker_id == prev.speaker_id
            and (cue.end - cue.start) < MERGE_BELOW_SECS
            and len(prev.text) + len(cue.text) + 1 <= _MERGE_MAX_CHARS
            and (cue.end - prev.start) <= _MERGE_MAX_SECS
        )
        if can_merge:
            merged[-1] = replace(prev, end=cue.end, text=f"{prev.text} {cue.text}")
        else:
            merged.append(replace(cue))

    out: list[Cue] = []
    for i, cue in enumerate(merged):
        end = cue.end
        wanted = cue.start + _required_duration(cue.text)
        if wanted > end:
            limit = cue.end + _MAX_EXTENSION_SECS
            if i + 1 < len(merged):
                limit = min(limit, merged[i + 1].start - MIN_GAP_SECS)
            end = max(end, min(wanted, limit))
        out.append(replace(cue, index=len(out) + 1, end=end))

    return replace(transcript, cues=out)
