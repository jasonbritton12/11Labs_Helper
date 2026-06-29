"""Normalize a Scribe response into an internal transcript model.

The canonical model is the single source of truth from which every deliverable
(SRT / VTT / DOCX / JSON) is rendered.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..elevenlabs.models import TranscriptionResult, Word

# Cue-splitting heuristics for readable subtitles.
_MAX_CUE_SECS = 5.0
_MAX_CUE_CHARS = 84
_GAP_SPLIT_SECS = 1.0
_SENTENCE_END = (".", "?", "!", "…")


@dataclass
class Cue:
    index: int
    start: float
    end: float
    text: str
    speaker_id: str | None = None
    is_audio_event: bool = False  # cue is entirely non-speech (e.g. "(music)")


@dataclass
class Transcript:
    cues: list[Cue] = field(default_factory=list)
    full_text: str = ""
    language_code: str | None = None
    multi_speaker: bool = False

    def speaker_label(self, speaker_id: str | None) -> str:
        """Human label like 'Speaker 1' from an id like 'speaker_0'."""
        if not speaker_id:
            return "Speaker"
        digits = "".join(ch for ch in speaker_id if ch.isdigit())
        if digits:
            return f"Speaker {int(digits) + 1}"
        return speaker_id


def caption_lines(transcript: "Transcript") -> list[str]:
    """Per-cue caption text (one per cue, same order) using subtitle conventions:

    - Speaker labels are NOT printed; instead ``- `` is prepended to a cue only
      when its speaker differs from the previous *dialogue* cue (a speaker change).
    - Pure audio-event cues (e.g. ``(music)``) carry no speaker treatment and do
      not count as a speaker change.
    """
    out: list[str] = []
    prev_speaker: str | None = None
    seen_dialogue = False
    for cue in transcript.cues:
        if cue.is_audio_event:
            out.append(cue.text)
            continue
        text = cue.text
        if seen_dialogue and cue.speaker_id != prev_speaker:
            text = f"- {text}"
        prev_speaker = cue.speaker_id
        seen_dialogue = True
        out.append(text)
    return out


def _token_text(w: Word) -> str:
    if w.type == "audio_event":
        inner = w.text.strip().strip("()[]")
        return f"({inner})"
    return w.text


def build_transcript(result: TranscriptionResult) -> Transcript:
    tokens = [
        w for w in result.words
        if w.type in ("word", "audio_event") and w.start is not None and w.end is not None
    ]
    speakers = {w.speaker_id for w in tokens if w.speaker_id}
    multi = len(speakers) > 1

    cues: list[Cue] = []
    cur: list[Word] = []
    cur_len = 0  # running character length of the current cue (avoids O(n^2) rejoins)

    def flush() -> None:
        if not cur:
            return
        text = " ".join(_token_text(w) for w in cur)
        text = " ".join(text.split())  # collapse whitespace
        cues.append(
            Cue(
                index=len(cues) + 1,
                start=cur[0].start,
                end=cur[-1].end,
                text=text,
                speaker_id=cur[0].speaker_id,
                is_audio_event=all(w.type == "audio_event" for w in cur),
            )
        )

    for w in tokens:
        if cur:
            prev = cur[-1]
            split = (
                w.speaker_id != prev.speaker_id
                or (w.start - prev.end) > _GAP_SPLIT_SECS
                or (w.end - cur[0].start) > _MAX_CUE_SECS
                or cur_len >= _MAX_CUE_CHARS
                or (_token_text(prev).rstrip().endswith(_SENTENCE_END) and cur_len > 30)
            )
            if split:
                flush()
                cur = []
                cur_len = 0
        cur.append(w)
        cur_len += len(_token_text(w)) + 1
    flush()

    full_text = result.text or " ".join(_token_text(w) for w in tokens)
    return Transcript(
        cues=cues,
        full_text=full_text.strip(),
        language_code=result.language_code,
        multi_speaker=multi,
    )
