"""Pydantic models for ElevenLabs Speech-to-Text responses.

Lenient by design (``extra='ignore'``) so new API fields never break parsing.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class Word(BaseModel):
    model_config = ConfigDict(extra="ignore")

    text: str = ""
    start: float | None = None
    end: float | None = None
    # "word" | "spacing" | "audio_event"
    type: str = "word"
    speaker_id: str | None = None
    logprob: float | None = None


class TranscriptionResult(BaseModel):
    """Parsed response from the STT convert endpoint."""

    model_config = ConfigDict(extra="ignore")

    text: str = ""
    words: list[Word] = Field(default_factory=list)
    language_code: str | None = None
    language_probability: float | None = None
    audio_duration_secs: float | None = None

    def offset(self, seconds: float) -> "TranscriptionResult":
        """Return a copy with every timestamp shifted by ``seconds`` (chunk stitching)."""
        shifted = []
        for w in self.words:
            shifted.append(
                w.model_copy(
                    update={
                        "start": None if w.start is None else w.start + seconds,
                        "end": None if w.end is None else w.end + seconds,
                    }
                )
            )
        return self.model_copy(update={"words": shifted})
