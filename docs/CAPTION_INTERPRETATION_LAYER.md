# Caption Interpretation Layer Plan

*Status: packets P00–P11 for C1–C3 and the renewed independent P13 review pass
at `84dd7c0` on `codex/caption-rulebook` as of 2026-09-29. C4 F1 exact rational
frame projection is implemented as an isolated core; its QC/export integration,
all delivery profiles, and shot context remain unimplemented. See the
[C3 release verification record](caption-handoff/C3_RELEASE_VERIFICATION.md). The
executable build packets and acceptance gates are in
[Caption Implementation Handoff](CAPTION_IMPLEMENTATION_HANDOFF.md). That
handoff governs details where this architecture overview is less specific.*

## Purpose

Turn the stored semantic transcript into readable, delivery-ready caption events
using the house standard in
[universal-caption-authoring-rule_608-708-web.md](universal-caption-authoring-rule_608-708-web.md).
The rulebook is the default policy for prerecorded English captions; an explicit
destination profile may override it.

The house rulebook is the governing authoring policy. Other readability advice
may rank choices only within its parameters; it cannot silently relax the rules.

The legacy `readability.retime()` transform remains a Phase-1 compatibility
baseline. The interpretation layer now owns event segmentation, authored line breaks,
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

Both caption timing modes use this layer. In `house` mode it authors segmentation,
lines, and timing. In `source` mode it keeps the existing canonical cue count,
starts, and ends derived from ElevenLabs word timestamps, authors only line
breaks, and reports any rule violations. Source mode never splits or merges cues
or silently retimes them to obtain a pass.

Settings exposes **Keep ElevenLabs timing (SRT/VTT)**. Fresh installs default
to house mode; existing saved choices migrate explicitly. Jobs capture their
options when staged, and Re-export offers an explicit per-export override.

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
  `blocker`), event/source reference, measured value, threshold, and
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

### C1 — Foundation and compatibility — implemented on feature branch

- Add the models, versioned house profile, destination-override resolution, and
  structured QC report.
- Migrate `readable_subtitles=True` to `caption_timing_mode="house"` and `False`
  to `"source"`; persist the new timing enum and `caption_profile_id`. Keep an
  explicit legacy API adapter during transition, not two competing booleans.
- Add the Settings control, job option snapshots, and explicit re-export/CLI
  overrides described in the handoff.
- Route both SRT/VTT modes through one `CaptionDocument` and QC report. In source
  mode, preserve canonical cue boundaries and report unresolved timing/density
  exceptions. Keep legacy renderer entry points only as compatibility adapters.

### C2 — Deterministic authoring rules — verified on feature branch

- Replace the 84-character cue heuristic for readable outputs with event
  segmentation and explicit 32-by-2 line composition.
- Implement CPS warning/failure bands, 1–7 second duration bounds, overlap/gap
  handling, speaker-change constraints, and source-trace preservation.
- Validate displayed glyph membership against the pinned libcaption CEA-608
  repertoire and report every miss. This is a repertoire check only; it does
  not generate 608 bytes or establish delivery/player compliance.
- Produce a CLI-readable and machine-readable QC report.

### C3 — Review workflow — verified on feature branch

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

C1–C3 are complete on this feature branch: house-mode SRT/VTT exports deterministically apply the
versioned profile, source mode preserves its cue timing/count ledger, both modes
explicitly author lines and emit visible structured QC, and all preserve the
Manual-Dub timing invariant. Glyph evidence and editorial coverage must be
explicit, with no unsupported compliance claim. The C3 workflow adds source-bound
caption-only edits and issue-scoped local approvals without changing the canonical
transcript or Manual-Dub timing. C4 capabilities are claimed only for destination
formats and context inputs that have their own verified profiles and fixtures.
