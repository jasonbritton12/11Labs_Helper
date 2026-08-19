# Caption Interpretation Layer Plan

## Purpose

Turn the stored semantic transcript into readable, delivery-ready caption events
using the house standard in
[universal-caption-authoring-rule_608-708-web.md](universal-caption-authoring-rule_608-708-web.md).
The rulebook is the default policy for prerecorded English captions; an explicit
destination profile may override it.

The current `readability.retime()` transform is a useful Phase-1 baseline, but it
only adjusts duration, reading speed, gaps, and a narrow same-speaker merge case.
The interpretation layer must also own event segmentation, authored line breaks,
QC severity, glyph compatibility, speaker-change treatment, and any frame- or
edit-aware timing adjustments.

Caption positioning and styling are explicitly out of scope. The layer and its
renderers must not emit placement, alignment, font, color, size, or other styling
directives. Presentation remains the responsibility of the destination player or
downstream delivery system.

## Architectural boundary

```text
TranscriptionResult
  -> canonical Transcript
  -> speaker-edit overlay
  -> caption interpretation layer (profile + optional context)
  -> CaptionDocument + CaptionQCReport
  -> SRT / WebVTT / future 608, 708, IMSC, and TTML renderers

Edited canonical Transcript
  -> Manual-Dub CSV (waveform timing remains untouched)
```

The canonical transcript remains immutable and continues to be the semantic
source of truth. The interpretation layer returns a new caption document; it
must never rewrite the history JSON or speaker-edit overlay. Manual-Dub CSV
generation stays outside this layer so subtitle authoring cannot change dubbing
clip boundaries.

## Proposed model

- `CaptionProfile`: versioned rules and destination overrides, including line
  length/count, CPS thresholds, duration bounds, frame rate, gap policy, glyph
  repertoire, and speaker notation.
- `CaptionContext`: optional information not present in Scribe output, such as
  frame rate, shot-change times, target format, and editorial approvals.
- `CaptionEvent`: interpreted start/end, explicitly authored text lines,
  speaker/content semantics, and stable references back to the source cue or
  word range.
- `CaptionDocument`: ordered interpreted events plus profile/rule version and
  provenance. Renderers consume this instead of deciding line breaks themselves.
- `CaptionQCIssue`: rule ID, severity (`info`, `warning`, `failure`, or
  `approval_required`), event/source reference, measured value, threshold, and
  suggested resolution.
- `CaptionQCReport`: aggregate pass/warn/fail result and a machine-readable list
  suitable for the GUI, CLI, logs, or a future sidecar report.

Keep the deterministic core in the engine. A language-aware boundary scorer may
rank candidate breaks using punctuation and syntax, but it must not paraphrase,
delete, or invent dialogue. Optional AI or video-analysis adapters can supply
context later; core export must remain reproducible without them.

## Rulebook interpretation

| Rulebook area | Interpretation-layer behavior |
|---|---|
| Text density | Hard limit of 32 displayed characters per line and two lines per event. Prefer one line and emit explicit line breaks. Speaker/SFX notation counts. |
| Reading speed | Target at or below 17 CPS; 17–20 CPS is a warning/approved exception; above 20 CPS is a failure unless explicitly approved. Never alter meaning to manufacture a pass. |
| Duration | Enforce 1.0–7.0 seconds where timing space permits, prohibit overlaps, and use frame-aligned boundaries when frame rate is known. Impossible combinations become QC issues rather than silent truncation. |
| Line breaking | Score natural punctuation, clause, conjunction, and pause boundaries; penalize the prohibited phrase splits and orphaned one- or two-word second lines. |
| Positioning | Intentionally not applied. Emit no positioning or styling metadata; player/downstream defaults control presentation. |
| Caption content | Preserve meaningful dialogue and recognized audio events. Content relevance, off-screen speaker identification, music/lyric treatment, and ambiguous background sounds require editorial review when the transcript lacks enough evidence. |
| Characters/glyphs | Validate against the resolved destination repertoire. Report every unsupported character with its source location; never silently replace or drop it. |
| Speaker changes | Prefer one speaker per event. When sharing is unavoidable, author one speaker per line and include notation in density/CPS calculations. |
| Timing/edit awareness | Anchor to associated speech, avoid excessive hangs, and respect shot changes when context exists. Revalidate after frame-rate conversion. |
| Delivery principle | Interpret one semantic master, then render all requested delivery formats from the same `CaptionDocument`. Destination-specific profiles override house defaults. |

## Resolution order

1. Load the versioned house profile.
2. Apply explicit destination overrides.
3. Normalize semantic content without changing wording.
4. Segment events and compose explicit lines.
5. Fit timing within speech, neighboring events, duration, CPS, frame, and edit
   constraints.
6. Validate density, CPS, duration, overlaps, speaker treatment, glyphs, and
   required editorial context.
7. Return the interpreted document and QC report; rendering is a format-only
   operation after this point.

If all constraints cannot be satisfied simultaneously, preserve text accuracy
and synchronization, return the best non-destructive interpretation, and emit a
failure or approval-required issue. Do not hide the exception.

## Delivery phases

### C1 — Foundation and compatibility

- Add the models, versioned house profile, destination-override resolution, and
  structured QC report.
- Preserve the existing `readable_subtitles` setting by mapping `True` to the
  house profile; introduce a future `caption_profile` setting without breaking
  saved settings.
- Route SRT/VTT through `CaptionDocument` only when readable output is selected.
- Keep the current raw subtitle path available until parity fixtures pass.

### C2 — Deterministic authoring rules

- Replace the 84-character cue heuristic for readable outputs with event
  segmentation and explicit 32-by-2 line composition.
- Implement CPS warning/failure bands, 1–7 second duration bounds, overlap/gap
  handling, speaker-change constraints, and source-trace preservation.
- Add destination-aware glyph validation, including a 608-compatible profile.
- Produce a CLI-readable and machine-readable QC report.

### C3 — Review workflow

- Add a caption preview/QC surface showing authored lines, timing, CPS, warnings,
  failures, and the originating transcript range.
- Allow explicit exception approval with a reason; persist approvals as a
  separate overlay so canonical data remains unchanged.
- Add manual controls for line breaks, event split/merge, speaker notation,
  and sound/music treatment.

### C4 — Frame, edit, and destination intelligence

- Accept frame rate and shot-change metadata; align timing and revalidate after
  frame-rate conversion.
- Add versioned 608, 708, WebVTT, SRT, IMSC, and TTML delivery profiles as those
  exporters are implemented.
- Evaluate optional video/AI context adapters separately; they may recommend
  editorial decisions but may not silently change caption meaning.
- Keep all renderers style-free: destination support does not authorize emitted
  placement, alignment, font, color, size, or other presentation directives.

## Verification matrix

- Unit fixtures for every hard limit, warning band, exception, and prohibited
  line-break pattern in the rulebook.
- Golden caption fixtures covering fast dialogue, two speakers, audio events,
  lyrics/music, long names, punctuation, accented text, unsupported glyphs,
  dense timing, shot changes, and frame-rate conversion.
- Property tests proving ordered events never overlap and authored lines never
  exceed the resolved profile unless a corresponding failure is reported.
- Regression tests proving the source transcript and speaker overlays remain
  unchanged and Manual-Dub CSV output is byte-identical with readable captions
  enabled or disabled.
- Cross-renderer tests proving SRT/VTT and future formats originate from the same
  interpreted events rather than reflowing independently.
- GUI/CLI acceptance tests proving warnings, failures, and approvals are visible
  and reproducible after save/reopen/re-export.
- Packaged macOS runtime smoke test for caption preview, QC navigation, and
  export after the new UI is introduced.

## Exit criteria

C1–C2 are complete when readable SRT/VTT exports deterministically apply the
versioned house profile, explicitly author their lines, emit structured QC, and
preserve the Manual-Dub timing invariant. C3 is required before claiming an
editorially complete workflow. C4 capabilities are claimed only for destination
formats and context inputs that have their own verified profiles and fixtures.
