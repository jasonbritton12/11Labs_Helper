# Dubbing Workflow Optimization (EN → ES via ElevenLabs Dubbing Studio)

*Status: Phase 1 implemented on the `dubbing-workflow` branch — July 2026.*
*Facts below verified against ElevenLabs docs/help center July 2026; re-verify pricing before relying on it.*

## Current workflow and its costs

We upload English originals via the web UI, build a Dubbing Studio project, fix
speaker/clip assignment by hand in the Studio, let ElevenLabs translate, then
edit and render Spanish dubs + subtitles.

**How dubbing is billed** (both paths, per *source-audio minute per target language*):

| Path | Cost |
|---|---|
| Subscription credits — automatic dub | ~2,000 credits/min (watermarked ~3,000 w/o) |
| Subscription credits — Dubbing Studio | ~5,000 credits/min watermarked, ~10,000 w/o |
| API billing — automatic | ~$0.33/min (watermarked), ~$0.50/min (clean) |
| API billing — Dubbing Studio | ~$0.50/min |

Studio projects include a limited free-regeneration allowance; after it's
exhausted, every regenerated clip bills against quota. **Action item: check
which billing path our account actually uses** (Settings → Subscription/Usage);
several decisions below change value depending on the answer.

## Answers to our strategy questions

### 1. Does uploading our English script alongside the video help?
**Yes — via Manual Dub, but the win is time and regen avoidance, not a credit discount.**
Dubbing Studio's **Manual Dub** option accepts the video (plus optional separate
foreground/background audio) and a CSV script with columns
`speaker,start_time,end_time,transcription,translation`. The project then opens
with our exact clips and speaker assignments — no in-Studio reassignment pass.
Billing is per source minute regardless, so credits don't drop, but we skip the
most tedious setup step and avoid paid regenerations caused by wrong
speakers/text. (The API's `mode=manual` equivalent is documented as
experimental; use the web UI Manual Dub upload.)

### 2. Should we QC speaker assignment before upload?
**Yes — now implemented in this app.** After transcription, use **⋯ → Review
speakers…** on a finished job to rename speakers (e.g. "MARIA") and reassign
mis-diarized cues, then export the **Dubbing CSV (Manual Dub)** deliverable.
Edits are stored as an overlay next to the app's history JSON, so re-exports are
free and repeatable.

### 3. Can dialogue (waveform) timing and subtitle (readable) timing be separated?
**Yes — now implemented.** The Dubbing CSV always keeps waveform-aligned timing
(dubbing needs it). SRT/VTT can optionally be re-timed for readability — min
1s display, ≤17 chars/sec reading speed, tiny same-speaker fragments merged,
~2-frame gaps preserved — via the "Readable subtitle timing" checkbox in
Re-export (default configurable via `readable_subtitles` in settings.json).
This is the timing-only Phase-1 baseline. The planned
[caption interpretation layer](CAPTION_INTERPRETATION_LAYER.md) will apply the
[universal 608/708/Web house rule](universal-caption-authoring-rule_608-708-web.md)
to segmentation, authored line breaks, timing, speaker treatment, glyph checks,
destination overrides, and structured QC. The Dubbing CSV remains outside that
layer and keeps exact waveform timing.

### 4. Is an external EN→ES translation step worth it? Does supplying Spanish save credits?
**No credit savings — dubbing bills per minute whether or not ElevenLabs
translates.** But supplying our own translation in the CSV `translation` column
means the Studio project starts with final, QC'd Spanish → dramatically fewer
edit/regenerate cycles (which do cost credits past the free allowance), plus
control over terminology/style. Recommended: **Phase 2** — a translation pass
(Claude API or DeepL with a project glossary) that fills the `translation`
column in the exported CSV, QC'd in-app before upload.

### 5. Should we separate dialogue from background ourselves?
**Sometimes.** ElevenLabs does its own separation (and `drop_background_audio`
exists API-side), but when we have real stems, Manual Dub accepts separate
foreground (dialogue) and background files — upload them for cleaner dubs and a
true stereo bed. When we don't, a local separation step (Demucs/htdemucs runs
fine on Apple Silicon) can produce a dialogue-only track for dubbing and a
stereo music/effects bed for the final mix instead of mono. **Phase 3** —
worthwhile once Phases 1–2 are routine.

### 6. Should we build our own app around the dubbing API instead?
**Not yet — hybrid is the right shape.** The Dubbing Resource API supports
everything the Studio does (per-segment transcription/translation edits, dub
regeneration, voice assignment, rendering), so a fully scripted pipeline is
possible, including "same speaker → same voice" control via speaker-level voice
assignment. But it re-implements the Studio's editorial UI we actually like.
The plan: keep the Studio as the editing surface, keep moving prep work (speaker
QC, script, translation) upstream into this app, and revisit direct API
submission (`POST /v1/dubbing` + polling) once prep is automated — likely first
as "create the Studio project from the app" rather than replacing the Studio.

### 7. Other optimizations
- **Watermark**: if outputs allow it, watermarked Studio dubbing halves credit cost on subscription plans.
- **Trim before upload**: dubbing bills per source minute — cut bars/slates/silence first (`start_time`/`end_time` exist API-side too).
- **`num_speakers` hint** improves diarization when speaker count is known (already supported in this app's STT options).
- **One language at a time**: each target language bills separately; don't add languages speculatively.
- **Re-use this app's free re-export** for all subtitle format needs — never re-transcribe for a format change.

## Phased roadmap

| Phase | What | Status |
|---|---|---|
| 1 | Speaker QC dialog, Manual-Dub CSV export, readable-subtitle re-timing | **Done (this branch)** |
| C1–C4 | Universal caption interpretation layer and editorial QC workflow | Planned — see [caption plan](CAPTION_INTERPRETATION_LAYER.md) |
| 2 | EN→ES translation pass (Claude/DeepL + glossary) filling the CSV `translation` column, with QC UI | Planned |
| 3 | Video input (ffmpeg), optional Demucs stem separation, direct dubbing-API project creation | Planned |

## Phase-1 usage (the new loop)

1. Drop the episode audio (`.mp3`) → **Run** → transcript with diarization.
2. **⋯ → Review speakers…** — rename to character names, fix any mis-assigned cues, Save.
3. **⋯ → Re-export…** — check **Dubbing CSV (Manual Dub)** (+ SRT/VTT with
   *Readable subtitle timing* for delivery subs). Free, from stored history.
4. In ElevenLabs → Dubbing Studio → **Manual Dub**: upload video (+ stems if we
   have them) + the exported CSV. Project opens with correct clips/speakers.
5. Edit translation/performance in the Studio as usual; render dub + pull ES subtitles.
