# Caption baseline (P00)

Recorded 2026-09-19 from the current `main` behavior. The fixture set is versioned
as schema version 1 in `tests/fixtures/captions/` and is intentionally independent
of any future caption implementation.

The canonical builder groups timestamped words by speaker, sentence, gap, five-second
duration, and its 84-character heuristic. It does not author 32-character lines or
attach source-word references. `caption_lines()` adds `- ` only when a dialogue
speaker changes; an audio-event cue neither receives a dash nor changes the speaker
used for the next dialogue cue.

The rapid-reply fixture preserves a 50-character cue from 0.0 to 0.5 seconds. The
raw cue measures 100 CPS. Existing readability retiming extends it to 0.517 seconds,
which measures 96.71179883945841 CPS, and extends the 0.1-second reply to 1.6
seconds. This is a captured counterexample, not an acceptance claim for the future
house profile.

The baseline export hashes cover canonical SRT, WebVTT, and Manual Dub CSV bytes for
representative transcripts. Manual Dub CSV remains dialogue-only and retains source
timing; readability changes subtitle timing without changing CSV bytes. The fixture
tests recompute these values and independently verify cue duration, CPS, character
counts, timestamp ordering, and the 32/33, 64/65, 17/20, 1/7 boundaries.

Malformed and untimed input is retained as raw fixture data so later source/QC layers
can report it explicitly. It is not silently parsed into a fabricated cue.
