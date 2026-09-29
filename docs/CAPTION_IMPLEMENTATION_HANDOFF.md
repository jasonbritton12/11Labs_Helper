# Caption rulebook implementation handoff

Prepared 2026-09-18. Implementation update 2026-09-29: packets P00–P11 and the
renewed independent P13 review pass at `84dd7c0` on
`codex/caption-rulebook`. P12's separate C4 plans are complete, and F1's isolated
exact rational frame-projection core is implemented and reviewed. F2 QC/export
integration and all destination behavior remain unimplemented. Evidence is
recorded in
[caption-handoff/C3_RELEASE_VERIFICATION.md](caption-handoff/C3_RELEASE_VERIFICATION.md)
and [C4 F1 verification](caption-handoff/C4_F1_VERIFICATION.md), with the plan set indexed in
[caption-handoff/C4_PLAN_INDEX.md](caption-handoff/C4_PLAN_INDEX.md).

## 1. Goal and starting point

Implement one caption-authoring pipeline governed by
[Universal Caption Authoring Rule — 608 / 708 / Web](universal-caption-authoring-rule_608-708-web.md).
Other readability guidance may improve choices within that rulebook's parameters.
Provide a saved Settings option to keep the timing derived from ElevenLabs output.
Render SRT and WebVTT from the same authored document, expose QC, and preserve
Manual Dub CSV, canonical history, and speaker edits.

Baseline inspected: local `main` and fetched `origin/main` at
`ec777c7818b6f07ec1c234017f17b23a606d96f5`, project version `0.2.0`.
`dubbing-workflow` remains at `2bd5cff`; its changes and the experimental Voice
Isolation utility are already ancestors of this `main`. The implementation branch
was created as `codex/caption-rulebook` from that baseline. Nothing has been
committed, pushed, merged, or published as part of the implementation run yet.

Baseline verification on 2026-09-18: the non-billable suite in section 10 passed
**96 tests in 19.80 seconds**, with the two live API modules explicitly excluded.
The sandboxed attempt had 62 passes and 34 setup errors because mock-server
loopback socket binding was denied; rerunning with permitted local sockets passed.
This verifies the current baseline, not any planned caption behavior, glyph
repertoire, packaged caption feature, or real Studio import.

The following was the baseline behavior before this branch and is retained here
as implementation rationale:

- `readability.retime()` attempts minimum duration, 17 CPS, a fixed 0.083-second
  gap, and limited same-speaker merging. It can miss these targets without QC.
- `canonical.build_transcript()` uses 84-character/5-second heuristics, not authored
  32-by-2 captions. Its size check can also overshoot before the next token.
- SRT/VTT output cue text without authored wrapping. Speaker-change dashes are
  added after timing calculation, so current CPS calculations omit that notation.
- `readable_subtitles=False` is persisted; only Re-export exposes its checkbox.
  **Settings has no caption timing control.**
- Both processor export paths and job-ID re-export use the setting. CLI JSON-path
  re-export calls the writer directly and ignores it.
- The word response has timestamps; it has no existing API-supplied caption events.
  The app creates cue boundaries. “Keep ElevenLabs timing” must describe this accurately.

A reproduced baseline counterexample: 50 characters spoken from 0.0 to 0.5 seconds,
with the next speaker starting at 0.6 seconds, becomes one 50-character line lasting
0.517 seconds, about 96.7 CPS, with no QC warning. Existing tests pass that behavior.

## 2. Decisions builders must preserve

### Governing policy

1. Preserve dialogue meaning, wording, order, and synchronization. Never manufacture
   a pass by truncation, paraphrase, omission, or unsupported-character replacement.
2. Apply a named, versioned destination specification when explicitly selected.
   Record every difference from the house profile; generic advice is not an override.
3. Otherwise use the 608/708/Web **house rulebook**. Its density limits, CPS bands,
   duration bounds, speaker/content handling, glyph checks, and synchronization
   requirements govern authoring and validation.
4. Use readability heuristics only to rank choices that satisfy those constraints:
   natural breaks, balanced lines, fragment merging, and bounded display extensions.
5. If rules cannot be satisfied together, retain a faithful draft and report the
   conflict. A requested source-timing preference is not automatic QC approval.

The house rulebook is a cross-format authoring policy, not a complete CEA encoder
or a certificate of conformance. The first release exports SRT/VTT only. No native
608, 708, TTML, or IMSC support is claimed until each has its own implementation,
verified destination profile, and acceptance fixtures.

Positioning and styling are excluded: emit no placement, alignment, font, color,
size, region, voice-tag presentation, or style blocks. The rulebook's positioning
section remains downstream presentation guidance, superseded for this app's output
by the agreed text-and-timing-only scope. Retain WebVTT's existing AI provenance NOTE;
it is a comment, not styling. Do not invent an SRT comment syntax.

### Timing control and default

Add a **Caption files (SRT/VTT)** group in Settings:

- Checkbox label: **Keep ElevenLabs timing (SRT/VTT)**.
- Checked: `caption_timing_mode="source"`.
- Unchecked: `caption_timing_mode="house"`.
- Help: “Keep cue boundaries derived from ElevenLabs word timestamps. Line breaks
  and caption checks still apply. Turn this off to author timing using the
  608/708/Web house rules. Dubbing CSV always keeps source timing.”
- Fresh installs default to **house**, with the checkbox unchecked.
- Existing saved choices migrate explicitly; do not silently flip them.
- Saving affects defaults for newly staged jobs. Existing jobs keep their captured
  options; Re-export offers an explicit per-export override without changing Settings.
- Disable the control when an individual export has neither SRT nor VTT selected.
  Do not erase its value when disabled. Voice Isolation has no caption control.

**Source mode guarantees**: build the unchanged baseline canonical cues, apply
speaker edits, and preserve each cue's count, order, start, and end. No timing
extension/shortening, split/merge, frame snapping, or shot snapping. This is the
app's existing grouping of ElevenLabs word timestamps, not byte-for-byte retention
of an ElevenLabs-generated SRT/VTT. Keep internal numeric times unchanged; exported
SRT/VTT use the existing millisecond rounding, validated again after serialization.

Source mode still composes line breaks and validates the house profile. If a fixed
cue exceeds 64 displayed characters, breaks cannot solve it: keep all text in a
flagged draft and report density failure. Report short/long duration, overlap,
fast reading, and unsupported glyphs; never “fix” those by violating the timing
choice. Source-mode manual split/merge and timing edits are disabled in C3.

**House mode guarantees**: resegment using source-word references, author explicit
lines, and fit timing under the resolved profile. New starts remain anchored to the
first associated source token; extensions are bounded by following speech/events,
known program duration, and the 7-second event limit. Real overlaps or impossible
fast dialogue become findings; moving speech arbitrarily is not a resolution.

### Compatibility and precedence

Use an enum, not two competing booleans. Persist `caption_timing_mode` and
`caption_profile_id`; retain `readable_subtitles` only as a deprecated migration/API
adapter during transition.

| Input | Resolved timing mode |
|---|---|
| Explicit new mode in export call/CLI | Explicit value |
| Explicit legacy `readable_subtitles=True` argument | `house` |
| Explicit legacy `readable_subtitles=False` argument | `source` |
| Saved new field | Saved value |
| Legacy settings field `True` / `False`, no new field | `house` / `source` |
| Older settings file with neither field | `source` to preserve the old default |
| No settings file / fresh settings object | `house` |

New and legacy arguments in the same call must agree; otherwise raise a clear
validation error before any output is replaced. New saved fields take precedence
over stale legacy fields; saving writes the new canonical fields and omits the
legacy field. Do not treat the old default `False` as an explicitly supplied API
argument: compatibility signatures must distinguish omitted values (`None`).

Resolve Settings through one pure helper, used by GUI and CLI. Valid settings
round-trip deterministically; an invalid new mode/profile produces a diagnostic,
not a quiet switch to another mode. Retain corrupt-file startup recovery, but
surface that the defaults were loaded. A read-only settings load must not rewrite
its file. No migration changes history JSON, speaker edits, or existing captions.

Capture a `CaptionExportOptions` snapshot in each transcription Job at staging.
Store it in the existing JSON-backed Job payload; no new SQLite column is needed.
For old Jobs without a snapshot, resolve once from migrated Settings at first
export and record `legacy_resolved_at_export` provenance. Do not infer old choices
from filenames. Changing Settings during processing must not change the snapshot.

Re-export resolution is: explicit per-export option > latest recorded export
options > staged Job snapshot > migrated Settings for legacy jobs. Re-export
records its resolved options as the latest export; the original staged snapshot
remains intact. JSON-path CLI re-export has no Job snapshot and uses explicit
options, then Settings. It does not infer or discover an unrelated edits overlay.

## 3. Source map: existing integration points

Paths below are relative to the repository root. Builders must read only their
packet's listed inputs plus the contracts in sections 2–7.

| Surface | Existing file and contract |
|---|---|
| Settings persistence | `elevenlabs_helper/engine/config.py`: `EngineSettings.load/save`, `readable_subtitles` |
| Settings UI | `desktop/widgets/settings_dialog.py`: `_save`; currently omits DUB_CSV and timing |
| Job snapshot/store | `engine/jobs/models.py`, `engine/jobs/store.py`; JSON payload plus status columns |
| Canonical cue IDs | `engine/exporters/canonical.py`: `Cue`, `Transcript`, `build_transcript`, `apply_edits`, `caption_lines` |
| Speaker overlays | `engine/edits.py`; keyed by current canonical cue index, not future caption IDs |
| Input timestamps | `engine/elevenlabs/models.py`: `Word`, `TranscriptionResult`; includes optional duration |
| Export dispatch | `engine/exporters/writer.py`: `write_deliverables`, `deliverable_paths` |
| Renderers | `engine/exporters/srt.py`, `vtt.py`; shared `caption_lines`, millisecond rounding |
| Initial/recovery export | `engine/processors/speech_to_text.py`: normal path and history fast path |
| Job creation/re-export | `engine/service.py`: `make_job`, `Engine.reexport`, `_load_result`, `delete_permanently` |
| CLI | `engine/cli.py`: `_settings_from_args`, `cmd_transcribe`, both `cmd_reexport` branches, parser |
| Per-job overrides | `desktop/widgets/job_options_dialog.py`; Options only before processing starts |
| Re-export UX | `desktop/widgets/reexport_dialog.py`, `desktop/reexport_action.py`; overwrite guard |
| Status/history UX | `desktop/windows/main_window.py`, `history_dialog.py`; terminal actions/status |
| Package registration | `pyproject.toml`: explicit setuptools package list; new packages need registration |
| Existing regressions | `tests/test_readability.py`, `test_exporters.py`, `test_dub_csv.py`, `test_speaker_edits.py`, `test_history_reexport.py`, `test_stage1.py`, `test_dialog_isolation_ui.py` |

`desktop/...` and `engine/...` in this table mean subdirectories of
`elevenlabs_helper/`. Do not change Voice Isolation, transcription billing, the Run
staging flow, or the canonical cue-splitting algorithm to implement caption policy.

## 4. Proposed modules and frozen interfaces

Add `elevenlabs_helper/engine/captions/` with `__init__.py`, `models.py`,
`profiles.py`, `source.py`, `compose.py`, `timing.py`, `qc.py`, `interpret.py`,
and later `overlays.py`. Keep UI-free functions deterministic and independently
verifiable. Register the package and any profile data in the wheel/PyInstaller
bundle. Avoid new runtime dependencies for C1–C2 unless measured necessity justifies one.

Use versioned Pydantic models for sidecar/overlay serialization; pure internal
helpers may use immutable dataclasses. Freeze these public contracts in P01:

```python
resolve_caption_options(settings, *, explicit=None, legacy_readable=None)
    -> CaptionExportOptions
build_caption_source(result, edited_transcript) -> CaptionSource
interpret_captions(source, options, context=None, overlay=None)
    -> CaptionInterpretation  # document + QC report
validate_document(document, source, profile, context=None)
    -> CaptionQCReport
render_caption_document(document) -> str  # separate SRT and VTT adapters
export_deliverables(result, out_dir, stem, deliverables, *,
                    edits=None, caption_options=None, context=None, overlay=None)
    -> ExportResult
```

`write_deliverables()` remains a compatibility wrapper returning
`dict[str, Path]`; new internal callers use `export_deliverables()` for structured
QC. The wrapper returns all files actually written, including caption sidecars.
Do not smuggle a QC object into a `dict[str, Path]` or fake a Deliverable enum value.
Preserve source mode for direct legacy wrapper calls with neither new options nor
an explicit legacy argument; app/CLI paths always pass resolved options and thus
use the fresh-install house default. This legacy wrapper default is an explicit
compatibility exception, not a third app mode. Document the additional artifact
keys as an intentional return-value expansion.

| Model | Required content |
|---|---|
| `CaptionExportOptions` | Timing enum, profile ID/version, export policy (`draft` or `strict`), schema version |
| `CaptionProfile` | Named/versioned rules, language scope, 32/2 limits, CPS 17/20 bands, duration 1/7 seconds, glyph repertoire version, optional verified destination overrides |
| `CaptionSourceToken` | Original result-word index, current canonical cue index, text/content kind, effective edited speaker, original optional numeric timestamps |
| `CaptionSource` | Tokens, baseline edited cues, source hash, speaker-overlay hash, language and optional duration |
| `CaptionContext` | Optional duration, exact rational frame rate, shot changes; absent inputs stay explicitly unknown |
| `CaptionEvent` | Stable ID, numeric start/end, authored lines, source token/character ranges, speaker/content semantics, timing-origin/mode |
| `CaptionDocument` | Schema/algorithm/profile versions, resolved options, source/edit/context hashes, ordered events, provenance |
| `CaptionQCIssue` | Stable issue ID/rule ID, severity, event/source refs, actual value/threshold, message, suggested resolution, optional approval reference |
| `CaptionQCReport` | Findings, severity counts, technical validation status, editorial coverage, exception state, resolved options, document hash |
| `CaptionInterpretation` | Document plus report; no file or GUI side effects |
| `ExportResult` | Paths actually written, optional interpretation/report, options, rendering disposition (`written`, `draft`, `blocked`, `not_requested`) |

IDs derive from source ranges plus deterministic segmentation/version information,
not wall-clock time or random UUIDs. Report hashes use a canonical serialization
excluding timestamps. Repeated authoring with identical inputs produces identical
events/findings and deterministic sidecars. Operational write time, if wanted,
belongs outside the hashed document/report. Unknown schema versions fail clearly.

### Source linkage and content preservation

Add a defaulted immutable `source_word_indices` tuple to `Cue`, populated in
`build_transcript()` while preserving its existing segmentation, text, times, and
indices exactly. Enumerate the original `result.words` before filtering so spacing
and missing timestamps never shift references. `apply_edits()` preserves this field.
Hand-built test Cues without references remain valid for old functions; the new
source adapter requires references or emits `SOURCE_TRACE_UNAVAILABLE`.

Reconcile all meaningful `word`/`audio_event` tokens against the cue map. Untimed or
unsupported token types carrying meaningful text must be reported, not silently
filtered as the current builder can do. A text-only result without timed words is
unrenderable as synchronized captions; do not invent timestamps. A genuinely empty
result is valid empty output, retaining “No speech detected” UX.

Speaker cue overrides map onto their source words **before** caption segmentation.
Do not key edits to newly renumbered caption events. Keep current canonical
normalization (single spaces and existing audio-event parentheses) as the explicit
baseline. Additional line breaks change layout only. Verify a content ledger:
source meaningful token IDs are consumed once in order; output wording matches
normalized source text after stripping recorded speaker notation and line breaks.
Do not use `full_text` as a substitute for timed tokens or lose dialogue hidden by
missing token timing.

## 5. Rule implementation contract

### Displayed text and composition

For house English v1, density/CPS use displayed Unicode code-point count, including
spaces, punctuation, speaker dashes, and sound notation; line separators and markup
escaping do not count. Multi-code-point combining sequences receive
`COUNTING_REVIEW_REQUIRED` until a validated counting policy exists; do not silently
normalize Unicode. Other language-specific counting policies require profiles.

Author speaker notation first, then calculate capacity and CPS. Preserve current
speaker-change dash conventions for the first release. Split at source word
boundaries; never split a single word just to hit 32. Prefer one line when text fits.
For two lines, enumerate whitespace break candidates with both lengths <=32 and
rank natural punctuation/clause/conjunction/pause boundaries, then balance.

Penalize article+noun, adjective+noun, name pairs, subject+verb, auxiliary+verb,
and preposition+phrase splits. Implement a small reviewed English heuristic list
and golden fixtures, not a claim of universal grammar recognition. Ambiguous
boundaries become editorial findings. Penalize a second line with only one or two
short words; use a better feasible break or mark `LINE_BREAK_REVIEW_REQUIRED`.
C2 tests establish deterministic composition; C3 establishes editorial review.

Source mode can only reflow inside an existing cue. House mode considers alternate
word-boundary segmentation within same-speaker blocks, bounded by audio-event,
speaker-change, and genuine long-silence boundaries. Avoid merging across long
silence merely to reduce cue count: use a named v1 `max_merge_gap_secs=0.25`
heuristic within the governing timing limits. Never merge across speaker/content
changes. A fallback single word exceeding capacity is preserved and failed.

Evaluate feasible event/line candidates together with available timing. Order
candidate cost lexicographically: content/sync integrity, number of hard-rule
failures, reading-speed target violations, linguistic/orphan penalties, excessive
hang, then event count. Stable ties choose earlier source boundaries. Implement
bounded dynamic programming or an equivalent deterministic search over source-word
boundaries, not a whole-program exponential search. Freeze scoring constants and
review goldens before integration. If no fully feasible choice exists, return the
best faithful draft and findings. Do not present a heuristic's failure as proof
that no possible editorial solution exists.

### Timing and QC

House event start equals its first associated token start. Its speech-end bound
is the **maximum end of all associated tokens**, not merely the final token's end:
overlapping words can have non-monotone ends. Source mode keeps the baseline cue
end exactly, but reports `SOURCE_CUE_EXCLUDES_SPEECH` if that cue boundary excludes
an associated token's end. Out-of-order starts receive an integrity/source-order
finding rather than silently sorting tokens. Extend display ends only after choosing segmentation;
never apply `readability.retime()` afterward. For a candidate:

```text
required_duration = max(1.0, displayed_characters / 17.0)
end_cap = min(start + 7.0, next_event_start, known_program_end,
              original_speech_end + 1.0)
```

Use only bounds that exist. `max_hang_secs=1.0` is a conservative, named v1
readability heuristic, not a quoted rulebook limit; if it prevents the CPS target,
report the measured exception. Render enough duration to reach the target if
possible; never cut the actual speech end to satisfy `end_cap`. Report source
speech already outside a bound. For fast dialogue, 17<CPS<=20 is a warning;
CPS>20 is failure unless a specific C3 exception is recorded. Duration <1 or >7,
overlap, and density/glyph violations are failures. Exact 17 and 20 boundaries
must be tested.

No fixed “two frames” without a known frame rate. C1–C2 use zero mandatory gap;
readability may prefer a gap only when feasible. A gap preference never shortens
source speech or creates a hard-rule failure. C4 supplies destination gap/frame
requirements through explicit profiles.

Validate source times for non-finite, negative, reversed, and zero-duration values.
Malformed/unrenderable timestamps block caption rendering and produce a report;
do not rely on current renderer clamping to hide them. Valid source overlaps are
preserved in source mode and failed in QC; house mode also preserves truthful
speech synchronization when an overlap cannot be resolved honestly. Revalidate
millisecond-rendered events: rounding can create zero duration, alter CPS, or lose
an intended gap. Apply the same rounding function to both renderers. Source mode
cannot alter timestamps to hide serialization violations.

The rulebook applies to prerecorded English. Unknown or other languages retain
content but report `LANGUAGE_PROFILE_UNVERIFIED`; never market the house English
heuristics as Spanish localization. Missing shot/frame metadata is recorded as
`not_evaluated` coverage, not a failed mathematical rule. Off-screen identity,
SFX relevance, music/lyrics, and ambiguous grammar are editorial checks with
`approval_required` findings when the source supplies insufficient evidence.
Do not invent names, lyrics, sound labels, or visual facts.

### Glyph evidence and destination scope

P01G must pin a primary specification or authoritative converter repertoire,
version, mapping, and source citation for the 608-compatible glyph check. Builders
must not assume `ASCII-only`, `Latin-1`, or arbitrary Unicode proves 608 support.
Record unsupported code points and source positions; retain them in draft output.
If validated repertoire evidence cannot be obtained, mark this check unverified
and block the “608-compatible authoring” claim. This evidence task is a dependency
of C2 completion, not permission to fabricate a table. Actual 608 byte generation,
control-code overhead, channel behavior, and downstream transcoding are C4 work.

A named destination override can change validated rules, but record its rationale
and version. Selecting WebVTT alone does not automatically waive the house density
or glyph policy. Exports in one batch consume one resolved document/profile;
different destination profiles require separate named export batches.

## 6. Export behavior, QC visibility, and recovery

Whenever SRT or VTT is requested, also write `<stem>.caption-document.json` and
`<stem>.caption-qc.json`, with artifact keys `caption_document` and `caption_qc`.
These are derived output artifacts, not a second canonical history or Deliverable
checkbox. Tell users “Caption exports include a caption document and QC report.”
No sidecars or authoring work for DOCX/JSON/CSV-only requests or Voice Isolation.
Existing `test_writer_emits_only_selected` must be updated intentionally for these
new sidecars; JSON-only and non-caption artifacts retain their contracts.

QC has two distinct dimensions: checked technical rules and editorial coverage.
Do not reduce missing coverage or an approved violation to a clean pass.

| Condition | Default `draft` export | Optional `strict` export | CLI result |
|---|---|---|---|
| Technical pass, editorial checks covered | Write captions + sidecars | Same | 0 |
| Warnings only | Write, show warning count | Same | 0; stderr summary |
| Unapproved failure or required approval | Write faithful, clearly reported draft + sidecars | Write document/report; block new SRT/VTT | 3 |
| Valid approved exception (C3) | Write, label exception | Write, label exception | 0; exception summary |
| Unrenderable source/integrity error | Report + diagnostic document; block SRT/VTT | Same | 3 |
| I/O/config/runtime error | Preserve recoverable input; report actual error | Same | 1 (existing missing-key usage path remains 2) |

Draft status belongs in the report, job message, preview, and CLI summary; do not
insert styling, warnings, or extra spoken text into caption content. A technically
passing caption is not a claim of complete editorial, converter, or player compliance.
C1–C2 do not accept approvals; findings remain actionable until C3 exists.

Keep JobStatus.DONE for completed processing with captions/diagnostics, but add a
backward-compatible optional `caption_qc_summary` and latest export-options fields
to Job JSON. UI says “Completed — caption QC failed”, “Caption export blocked”,
“Caption review required”, or “Completed — caption warnings”, as appropriate;
plain Completed is reserved for no actionable QC. Respect “No speech detected”.
Do not make QC failure a queue retry condition. It must never trigger a new upload
or paid transcription. Both normal and history fast paths use the same result adapter.

Build the full output plan before writing; update `deliverable_paths()` or replace
it with `planned_export_paths()` to include sidecars and strict-mode dispositions.
Preserve the GUI overwrite guard. If strict mode leaves an older SRT/VTT in place,
say “Previous caption file retained; this request produced no replacement” and
remove that kind from the latest export artifact record so it is not represented
as current. User files need not be deleted. Record paths actually written.

Treat the latest caption artifacts as **one document-bound export batch**. On any
new caption export attempt, retire every previous SRT/VTT/document/report entry
from the current batch and add only paths written from this attempt's document.
Keep unrelated DOCX/JSON/CSV entries. An unrequested old VTT after SRT-only
re-export is a retained user file, not a current caption artifact validated by
the replaced shared QC report. Persist the new batch's document hash, disposition,
and requested/written formats with its summary. List retained paths separately
in feedback when applicable; never delete them. DOCX/JSON/CSV-only exports do not
replace the last caption batch or its options/summary. Partial I/O failures record
actual replacements and mark the batch incomplete; they never inherit old captions
as if the new document validated them.

Render and serialize to same-directory temporary files, then atomically replace
each file after validation; failure removes temporary files and surfaces partial
commit information. Do not claim multi-file atomicity. Define/report which files
were replaced if a later replacement fails; never retry transcription to repair
this. A failed re-export preserves canonical history and edited overlays.

Derived sidecars expose transcript content like SRT/VTT; do not store absolute
source paths or credentials in them. App retention controls still govern canonical
history. C3 caption overlays in app history must join permanent deletion and
retention pruning, including orphan cleanup; output sidecars follow user output
ownership, like existing captions. Do not silently retain new private history
when `keep_history_json=False`.

## 7. Acceptance fixtures and independent checks

P00 creates versioned fixture JSON under `tests/fixtures/captions/`, containing
mock `TranscriptionResult`, optional speaker edits, mode/profile/context, and
expected words/times/findings. Prefer behavior-driven checks to implementation mirrors.
Use the existing pytest tools; a fixed-seed generator can check invariants without
adding Hypothesis. Test every hard boundary and every export path.

| Fixture | Required assertion |
|---|---|
| 32/33-char line, 64/65-char event | Explicit 32-by-2 composition or corresponding failure; preserve all words |
| 17.0 / just above 17 / 20.0 / above 20 CPS | Pass / warning / warning / failure; count notation |
| 0.999 / 1.0 / 7.0 / 7.001 seconds | Correct duration severity; source times unchanged |
| Baseline 50-char rapid speaker reply | Source: fixed 0.0–0.5 cue, authored lines, duration/CPS findings; density failure only if no feasible 32-by-2 break; house: faithful alternative with remaining failures reported |
| Same-speaker fragments separated by 0.1 vs 4 seconds | Merge only feasible nearby fragments in house; source never merges |
| Dense long same-speaker cue >64 chars | House uses source word boundaries; source retains cue and flags capacity |
| Single long word | Preserve whole word; report unresolved density |
| Article/noun, names, auxiliary/verb, orphan second line | Prefer natural feasible break; ambiguous cases produce review finding |
| Speaker change at exactly 32 characters | Dash included in line capacity and CPS |
| Cue-speaker reassignment and rename | Effective source-token speakers reflect current overlay; CSV remains stable across caption options |
| Music, meaningful SFX, dialogue | Preserve events; no false dialogue speaker-change dash; editorial relevance exposed |
| Accent, smart punctuation, musical symbol, emoji, combining sequence | Repertoire-backed result or explicit unverified/unsupported finding; no glyph loss |
| Untimed dialogue, text-only, malformed timestamps | Explicit source finding and blocked captions, not silent omission/invented time |
| Empty result | Valid empty captions; “No speech detected”; no fabricated approval need |
| Overlapping speakers, sub-ms duration, ms rounding boundary | Accurate failure after render quantization; never invent a clean pass |
| Earlier word ending after a later word | House speech-end bound uses maximum associated end; source preserves baseline end and flags excluded speech |
| Known program end before required extension | No extension past duration; report unmet rule |
| English / Spanish / unknown language | Correct verified scope and coverage; no English-only guarantee for Spanish |
| No frame/shot metadata | Coverage says not evaluated; no implied frame accuracy |
| Re-export twice and after restart | Deterministic document/report; options and approvals reproducible |
| No captions selected / Voice Isolation | No new sidecars, QC, or changed non-caption outputs |
| Strict failed re-export with preexisting captions | Old file untouched, status/report identify retained old file, no stale current artifact |
| Source SRT+VTT batch followed by house SRT-only | Old VTT retained on disk but retired from current batch; shared sidecars describe only the new batch |
| Strict failed SRT-only attempt after SRT+VTT | Both old caption files retained; neither is represented as validated by the diagnostic document/report |
| Disk failure during temp write or replacement | Canonical input safe; no paid retry; partial write report accurate |

Property-style assertions: source mode preserves the full cue timing/count ledger;
non-exception lines are <=32 characters and <=2 lines; every violation has a
source-linked issue; content token ledger is ordered and complete; source/history
and speaker overlays are unchanged; SRT/VTT parsed events match the document at
millisecond precision; neither renderer reflows; Manual Dub CSV is byte-identical
with source/house modes, profile changes, QC failures, and C3 caption edits.
Use an independent test parser/measurer, not production validation as the test oracle.

## 8. Execution packets for smaller models and agents

This is T2 implementation with a T3 kernel in segmentation/timing tradeoffs.
Use inexpensive coding models for narrow plumbing packets; use a mid-tier model
with more reasoning for authoring/integration; use a stronger independent reviewer
for policy seams and release verification. No model prices or fixed token budgets
are assumed. Give one worker one packet and its declared dependencies, not this
entire conversation. Each packet should fit one reviewable commit; split further
if it expands. Tests accompany behavior changes. Build tasks begin only when the
implementation is requested; this document authorizes no publishing or billable calls.

| Packet | Output contract | Route / pattern | Depends on | Hard verification |
|---|---|---|---|---|
| P00 | Baseline and independent acceptance fixtures | Cheap; tools | — | Golden data/counters; existing suite |
| P01 | Models, profile/options contract, package skeleton | Cheap–mid; generate/verify | P00 | Schema round-trip; independent limits |
| P01G | Pinned glyph repertoire and reference fixtures | Mid research; verify evidence | P01 | Reference/mapping provenance; supported/unsupported fixtures |
| P02 | Settings migration + Job option snapshots | Cheap–mid; generate/verify | P01 | Full migration and precedence table |
| P03 | Source references and content ledger | Mid; generate/verify | P01 | Canonical/CSV regression; untimed-content detection |
| P04 | Authored lines and segmentation candidates | Mid with reasoning; verify | P03 | Density, linguistic, ordering goldens |
| P05 | Timing search and complete QC | Mid with reasoning; strong critic | P04, P01G | Boundary tests, source immutability, overlap/rounding failures |
| P06 | Style-free document renderers + writer integration | Mid; generate/verify | P05, P02 | Parsed SRT/VTT parity; sidecar/write-failure tests |
| P07 | Service/processor/CLI integration | Mid; generate/verify | P06 | Every export path; mock billing counter; CLI exit codes |
| P08 | Settings/Options/Re-export controls | Cheap–mid; generate/verify | P07 | Offscreen persist/cancel/override tests |
| P09 | Read-only preview/QC visibility and status/history | Mid; generate/verify | P08 | Findings remain visible after restart; source navigation |
| P10 | C3 manual authoring overlay | Mid with reasoning; verify | P09 | Content ledger; source-mode restrictions; CSV invariance |
| P11 | C3 approvals/lifecycle | Mid with reasoning; strong critic | P10 | Approval invalidation; delete/prune/no-retention tests |
| P12 | C4 frame/edit context and verified destinations | Mid–strong; separate plans | C1–C3 gates | Rational frame/shot/profile-specific fixtures |
| P13 | Independent release verification and operator docs | Strong reviewer; fresh context | P09; again P11/P12 as delivered | Wheel/import/runtime; regression, QA, evidence report |

Sequence core P00→P01→P02/P03→P04→P05→P06→P07→P08→P09→P13.
P01G may run beside P02/P03. Parallel work is allowed only in separate checkouts
with disjoint file ownership and a frozen interface; integrate after checks pass.
Do not let two workers edit `writer.py`, `config.py`, or shared tests simultaneously.
P10/P11 now form the delivered C3 milestone; P12 implementation is explicitly deferred.

### P00 — Capture reference behavior

Read existing exporter, readability, speaker-edit, history and stage1 tests.
Own new fixture data and `tests/test_caption_fixtures.py`, plus a short baseline
report in `docs/caption-handoff/BASELINE.md`. Capture canonical cue times/text and
Manual Dub CSV bytes for representative transcripts, including the counterexample.
Tests for future behavior may be staged as documented expected failures only in
this packet; remove those marks as dependent packets land. Never hide preexisting
failures. Output no production code and verify fixture arithmetic with tools.

### P01 — Freeze the public model contract

Own `engine/captions/{__init__,models,profiles}.py`, package registration in
`pyproject.toml`, and `tests/test_caption_models.py`. Implement sections 2/4's enums,
strict schemas, house English v1, deterministic IDs/hashes, and immutable source
models. Separate structural parsing from QC acceptance: malformed source data
must survive in diagnostic input models long enough to report it, while renderable
CaptionEvents require finite valid times. A diagnostic document can have no events
and source-level findings. Serialize non-finite diagnostic values as a described
invalid value plus a finding, never non-standard JSON NaN/Infinity or invented
renderable time. Supply serializers and contract examples. Keep profiles
internal/versioned initially; no arbitrary JSON override file or profile picker
that silently relaxes rules. Hand off actual signatures and model JSON to later packets.

### P01G — Verify repertoire evidence

Own the pinned repertoire data/reference note under `engine/captions/` and
`docs/caption-handoff/GLYPH_EVIDENCE.md`, plus `tests/test_caption_glyphs.py`.
Obtain primary/authoritative mapping evidence, cite its exact version/source, and
verify licenses for copied data. Test accented letters, punctuation, music symbols,
and unsupported examples against the mapping. Mechanical representability and
actual delivery encoding remain separate checks. If evidence is unavailable,
produce an explicit coverage blocker instead of pretending the gate passed.

### P02 — Resolve/migrate settings and freeze job choices

Own `engine/config.py`, `engine/jobs/models.py`, `service.make_job`, and
`tests/test_caption_settings.py`. Implement the precedence/migration table exactly,
new defaults, pure resolver, warning on recovered settings, optional legacy
adapter, and staging/latest-export snapshots. Old Job JSON loads without a schema
migration; old settings load without losing unrelated values. Test explicit new
values overriding stale legacy data, disagreement errors, absent old fields,
unknown profiles, save/cancel semantics, and Settings changes during a staged job.
Make Settings persistence use same-directory temporary output and atomic replace
so the UI can commit changes into the shared settings object after save succeeds.
Do not connect the UI yet. Coordinate fields with P07 before it edits service.

### P03 — Build faithful caption source

Own `engine/captions/source.py`, minimal defaulted source refs in `canonical.py`,
and `tests/test_caption_source.py`. Preserve existing canonical output and index
keys. Attach original word indices during the same grouping pass; do not rerun
an approximate grouping algorithm in another module. Project speaker edits onto
source tokens, preserve audio-event semantics, reconcile omitted untimed content,
and implement the immutable content ledger and hash. Existing speaker/CSV tests
must remain byte-equivalent. A failure to map references is a finding, not guessed
alignment. Do not add caption-specific segmentation to `build_transcript()`.

### P04 — Compose candidates and explicit lines

Own `engine/captions/compose.py`, language heuristic fixtures, and
`tests/test_caption_compose.py`. Implement section 5's display-count policy,
notation-first budgeting, feasible line enumeration, one-line preference,
linguistic/orphan scoring, same-speaker bounded candidates, deterministic ties,
and faithful failed fallbacks. Source mode yields one candidate per fixed source
cue. Return typed candidates/source spans for P05; do not mutate source or discard
tokens. Test output with an independent counter and normalized token ledger.
Freeze candidate cost and search bounds in a small contract note for P05.

### P05 — Resolve timing, run QC, assemble interpretation

Own `engine/captions/{timing,qc,interpret}.py` and
`tests/test_caption_timing.py`, `test_caption_qc.py`, `test_caption_interpret.py`.
Combine candidate composition and timing space so segmentation is not chosen
blindly before discovering an avoidable timing failure. Implement best faithful
draft fallback, source-mode identity, all failure/warning bands, milliseconds
revalidation, glyph findings, language/editorial coverage, and deterministic
issue IDs. Validate independently generated adversarial fixtures. Review with a
fresh stronger critic for silent truncation, fake timing, missing source words,
notation-count mistakes, and unreported failures before P06 integration.

### P06 — Render documents and write verified outputs

Own `engine/exporters/{srt,vtt,writer}.py`, legacy readability deprecation adapter,
`tests/test_caption_renderers.py`, `test_caption_writer.py`, and intentional
adjustments to old exporter/readability integration assertions. Preserve legacy
`render(Transcript)` entry points as explicit legacy adapters for existing external
callers; add `render_caption_document(CaptionDocument)` for the new pipeline.
No new app export path calls the legacy renderer/retimer. Preserve only internal
baseline retimer tests while transition compatibility is tested explicitly.
Implement ExportResult/wrapper contracts, draft/strict dispositions, planned paths,
sidecars, same-directory temporary output, cleanup/partial-replace diagnostics,
and non-caption bypass. Escape format syntax only when displayed wording is
preserved; test literal `<`, `>`, `&`, arrow strings, blank-line injection, and
Unicode against primary WebVTT syntax and independent parse fixtures. Invalid
payloads are findings/errors, never unexplained text deletion. Extend packaging
checks for any profile data. Do not change Manual Dub CSV formatting.

### P07 — Connect every engine and CLI path

Own `engine/service.py` (excluding P02's finished model contract),
`processors/speech_to_text.py`, `engine/cli.py`, and tests
`test_caption_export_paths.py`, `test_caption_cli.py`; extend history/stage1 tests.
Use one effective-options/export-result adapter in initial and cached-history
paths. Add `--caption-timing {house,source}`, `--caption-profile house-english-v1`,
and `--caption-policy {draft,strict}` to transcribe and reexport; omitted flags
inherit resolved options. Job-ID `--out` should be honored rather than dropped;
JSON-path mode must use the same Settings policy, without discovering speaker
edits by filename. Invalid flags/config are explicit errors. Print QC/exception
summary to stderr, paths to stdout, and implement section 6's exit codes, including
multi-input aggregation (runtime/usage errors outrank QC code 3; warnings alone 0).
Persist the document-bound caption batch, report summary/latest caption options,
and remove all stale caption artifact entries as specified in section 6, including
unrequested formats. Assert zero new API calls on all re-export/QC/history-recovery paths.

### P08 — Expose consistent controls

Own `desktop/widgets/{settings_dialog,job_options_dialog,reexport_dialog}.py`,
`desktop/reexport_action.py`, and `tests/test_caption_settings_ui.py`.
Implement section 2's Settings checkbox/help, per-job snapshot override, and
per-export override seeded from latest resolved choices. Replace the old readable
checkbox label; do not show two competing toggles. Keep the legacy adapter in the
engine only. Make cancel non-mutating by editing a copy then committing after
validation and a successful settings-file save. Commit validated settings values
into the original `EngineSettings` instance in place: `Engine` and `JobQueue`
currently share it, and `MainWindow._open_settings()` does not rebind from the
dialog. Do not merely replace `dialog.settings` and lose the user's changes.
On save failure, leave both the original instance and persisted file unchanged
and show the actual error (use a temporary file/atomic replace for Settings save).
Preserve the current Options race guard for active jobs. Add DUB_CSV
to Settings/Options deliverable lists using the shared labels, so those surfaces
preserve an existing CSV selection. Include sidecars in the existing overwrite
prompt and distinguish strict retained captions from files just written. Test
keyboard labels, disabled-but-preserved values, restart persistence, and no paid
API call. Settings changes alone regenerate no files.

### P09 — Make QC usable before declaring C1–C2 done

Own new `desktop/windows/caption_qc_dialog.py`, integrations in `main_window.py`
and `history_dialog.py`, and `tests/test_caption_qc_ui.py`. Provide a read-only
“Review captions…” action with authored lines, times, CPS, profile/mode, source
ranges, findings, coverage, and a Reveal-report affordance. Display source-timing
mode and draft/blocked/exception status explicitly. Findings must survive window
close/reopen and app restart using current sidecar/Job metadata. Missing/moved
reports show a recovery message, never a fabricated pass; offer free regeneration
from retained history. No approvals or mutable editorial controls in this packet.
Also provide read-only review of a diagnostic report when rendering was blocked.
Use text/icons as well as color. Keep UI work separate from engine scoring.

### P10 — Add C3 authored-edit overlays

Own `engine/captions/overlays.py`, the edit extension to caption review UI,
the explicit overlay-loading extensions to `service.py` and both
`processors/speech_to_text.py` export adapters, and
`tests/test_caption_overlays.py`. Persist caption-only split/merge/line-break/
speaker-notation/SFX editorial operations using source refs plus source/profile/
algorithm hashes. Store overlays separately from original history and speaker
edits. C3 edits change layout/segmentation, not dialogue wording; wording changes
need a separate future transcript-edit design. Timing operations/structural
split-merge stay disabled in source mode. In house mode, only source-anchored
boundaries within validated constraints are allowed. Revalidate every edit;
content ledger and CSV invariance remain mandatory. If source/speaker/profile
changes invalidate alignment, flag the overlay for review rather than silently
reapplying it. Route job-ID paths through the same explicit job-overlay loader;
JSON-path mode may consume only an explicitly supplied overlay, never find one
by guessed filename. Add free re-export/restart acceptance tests. P10's service/
processor changes follow P07 and may not run concurrently with other owners of
those files.

### P11 — Approvals and storage lifecycle

Own approval models/logic in caption overlays/QC, integration in service/history
cleanup, approval UI, and `tests/test_caption_approvals.py`,
`test_caption_overlay_lifecycle.py`. Persist explicit issue-scoped reason,
local actor label, date, and hashes of source, speaker overlay, resolved profile,
caption document, and affected rule measurement. Changing any material bound
invalidates approval; regenerating an identical document does not. Approved
violations remain measured and listed with their exception status, never removed
or relabeled compliant. Content loss, non-finite times, and unrenderable data are
non-approvable integrity failures. A local approval is not an authenticated audit
signature. Join permanent deletion and age-based pruning/orphan cleanup; with
history off, keep editing ephemeral and do not create private overlays. Explicit
user export may still write derived sidecars to the chosen output folder.

### P12 — Future C4 packets, not core dependencies

After C1–C3, write separate narrow plans for: exact rational FPS/frame-alignment
and frame-rate conversion; shot-change context and hang checks; verified named
destination overrides; then one exporter at a time. The explicit order is shared
frame/context/override foundations, generic TTML2, then IMSC 1.3 Text. Native
CTA-608 and CTA-708 remain independent after the shared foundations and their
separate permitted-standard/clause-map gates. Preserve
text/timing-only scope. Source mode remains unsnapped, reporting destination
incompatibility. Each exporter requires primary-spec references, packaging, golden
round-trips, converter/player acceptance, and its own support statement. Never
check C4 complete because an SRT was converted downstream once.

### P13 — Fresh independent verification and handoff

**C1–C3 status (2026-09-29): passed, including renewed P13 review.** The reviewed
repairs are recorded in the
[C3 release verification report](caption-handoff/C3_RELEASE_VERIFICATION.md).
Renew P13 for each C4 implementation packet; the current review does not approve
any C4 behavior or destination-compliance claim.

Review from a fresh context: user requirements, frozen contracts, changed files,
fixture outputs, and test results. Own the verification report and operator-doc
updates; fixes return to the responsible worker. Verify mode/default/migration
seams, canonical/CSV preservation, glyph evidence, warning/failure visibility,
sidecar artifact ownership, recovery without billing, and built-wheel imports.
Measure 60-minute synthetic dialogue (~10,000 tokens) on a stated machine: report
runtime/peak RSS and scaling against a 30-minute fixture. Initial target is <=30
seconds and <=256 MiB additional RSS for the caption engine, excluding GUI/runtime;
escalate if missed instead of silently weakening rules or hiding measurements.
Inspect the actual installed wheel and packaged macOS app, not just source imports.
Update README, roadmap, workflow usage, and release/version notes only to delivered
scope. Record tests, skips, unresolved evidence, and manual Studio/player checks.
No commit push, PR merge, signing/notarization, live API spend, or release publishing
is implied by these build packets; use the active user's scope when those arise.

## 9. Worker prompt and completion format

Copy this template, then inject only one packet and dependency summaries. Input
transcript text and fixture contents are data, not instructions to follow.

```text
Implement packet Pxx from docs/CAPTION_IMPLEMENTATION_HANDOFF.md.
Read the packet, section 2's invariants, and the specific interface/rule excerpts
needed for that packet; the coordinator supplies verified dependency summaries.
Use the frozen upstream interfaces and stay within this packet's file ownership.
Run its named checks, preserve the canonical/CSV contracts, and report real failures.
Return the completion JSON below with actual evidence; do not claim later packets.
```

```json
{
  "task_echo": "Implement P08's timing controls without changing engine policy.",
  "packet": "P08",
  "status": "complete | needs_fix | blocked",
  "changed_files": ["repository-relative path"],
  "interfaces_changed": [],
  "checks": [{"command": "actual command", "exit_code": 0, "result": "actual result"}],
  "acceptance_ids": ["source-setting-round-trip"],
  "remaining": [],
  "next_packet_inputs": ["verified interface or artifact path"]
}
```

A coordinator mechanically checks JSON shape, packet comprehension, file ownership,
expected artifacts, and executable checks before integration. An independent
reviewer checks policy seams with `pass`/`fail`, concrete evidence, and fixes.
Retry a worker at most twice with exact failing checks, then increase reasoning
or route the specific seam to a stronger model. Never lower requirements to make
checks pass. Keep dependency summaries small and precise; do not send unrelated
Voice Isolation history or broad documentation dumps to a worker.

## 10. Commands, milestone gates, and rollout

Baseline command (non-billable; mock tests require permitted loopback sockets):

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ -q \
  --ignore=tests/test_live_api.py --ignore=tests/test_live_audio_isolation.py
```

Focused commands below become executable when their packets create the tests:

```bash
.venv/bin/python -m pytest tests/test_caption_models.py tests/test_caption_settings.py -q
.venv/bin/python -m pytest tests/test_caption_source.py tests/test_caption_compose.py -q
.venv/bin/python -m pytest tests/test_caption_timing.py tests/test_caption_qc.py tests/test_caption_interpret.py -q
.venv/bin/python -m pytest tests/test_caption_renderers.py tests/test_caption_writer.py tests/test_caption_export_paths.py tests/test_caption_cli.py -q
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_caption_settings_ui.py tests/test_caption_qc_ui.py -q
.venv/bin/python -m pytest tests/test_caption_overlays.py tests/test_caption_approvals.py tests/test_caption_overlay_lifecycle.py -q
.venv/bin/python -m pip wheel . --no-deps --no-build-isolation --wheel-dir /tmp/elevenlabs-caption-wheel
bash packaging/build_dmg.sh
```

Wheel gate: install that wheel without the checkout on PYTHONPATH into an isolated
environment; verify `engine.captions` import/profile data and CLI reexport on a
fixture. If a bundled runtime is used, record it. Package gate: launch the actual
bundle and inspect Settings, both modes, preview, QC failure, re-export/restart,
and Voice Isolation/Run regression. Live API and real Studio Manual Dub import
remain separate explicitly authorized checks, not ordinary unit-test dependencies.

| Milestone | Required exit evidence | Claims allowed |
|---|---|---|
| C1 foundation | P00–P03, migration/snapshots/source ledger/package contracts pass | Models/settings/source mapping implemented; authoring still incomplete |
| C2 enforced authoring | P01G, P04–P09, P13 pass; no expected-failure marks; glyph evidence pinned; both modes demonstrated | House-profile SRT/VTT authoring with structured technical QC and explicit editorial coverage |
| C3 review workflow | P10–P11 and renewed P13 pass | Editable captions and reproducible issue-scoped exceptions; editorial completeness only for reviewed coverage |
| C4 specific delivery | Individual P12 plans and renewed P13 per exporter/context | Only the verified formats/profiles/context behaviors actually delivered |

Implement in small reviewed commits on the caption branch. Preserve legacy source
settings on upgrade and document house defaults for fresh installs. Do not
regenerate existing output merely on startup or migration. Before merging C2,
review source-vs-house goldens and demonstrate the Settings choice, QC counterexample,
no-billing re-export, and invariant Manual Dub CSV. If rollout needs reversal,
return to the earlier app build and retained canonical inputs; old app versions
ignore new fields but will default legacy readable timing to False. Downgrades
therefore preserve source timing but do **not** retain the new caption policy;
warn operators to avoid rewriting approved outputs until re-export is deliberate.
Never recover by deleting canonical history or unreviewed user files.
