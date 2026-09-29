# Caption C3 release verification

Verification date: 2026-09-29

Branch/worktree: `codex/caption-rulebook`, uncommitted and unpushed
Verdict: **Pass for the implemented C1–C3 feature-branch scope**

## Verified scope

P10 adds source-bound caption-only overlays for split, merge, line-break,
speaker-notation, and sound/music treatment. It preserves wording and the source
token ledger. Source mode rejects structural split/merge and timing changes;
non-structural operations must match a complete fixed source cue. House changes
remain source anchored and are revalidated against profile, timing, hang, and
program limits.

Job re-export uses the job's explicit overlay record. JSON-path re-export accepts
only an explicitly supplied `--caption-overlay` path and never guesses a sibling
filename. Missing, stale, malformed, or mismatched overlays remain visible in QC,
and strict output cannot treat them as accepted. Re-export remains local and free;
Manual-Dub CSV continues to use canonical waveform timing.

P11 adds local, issue-scoped approval records with reason, actor label, approval
time, exact measurement, rule/event/source scope, source and speaker hashes,
resolved profile and algorithm hashes, and caption-document binding. Narrative-
only wording or regenerated issue-ID drift does not invalidate an otherwise
identical measured approval. Material changes invalidate it and produce visible
`CAPTION_APPROVAL_INVALIDATED` evidence.

Approvals do not remove findings, change their severity, or relabel technical
evidence as compliant. Ordinary non-actionable warnings and integrity failures
cannot be approved. Strict output succeeds only when every actionable violation
has a complete valid approval and no blocker remains. Missing, malformed, stale,
or sidecar-only approval references are not trusted.

Managed caption overlays and approvals join permanent deletion, age pruning, and
orphan cleanup. With history disabled, speaker edits, caption overlays, and
approvals stay in the live `Engine` only, are available for the current re-export,
create no private history files, and disappear after restart. User-selected
output files are not deleted by private-history cleanup.

## Independent review and repairs

The initial P10 review raised five findings around source/house edit boundaries,
stale or corrupt overlay visibility, program-bound timing, explicit overlay
loading, and re-export/CSV invariants. Those paths were repaired and the focused
re-review returned **Pass** with no remaining P10 blocker.

The initial P11 review raised four findings:

1. Approval matching depended on narrative-derived issue identity rather than
   only the material technical scope.
2. Ordinary warnings could enter an approval path.
3. The UI could display stale sidecar approval references without proving they
   existed in the current approval ledger.
4. History-off speaker edits were not consistently carried through the live
   engine re-export path.

The repairs bind approvals to material evidence, enforce actionability and
integrity exclusions, verify current ledgers in the UI, and keep all history-off
edits engine-ephemeral. The independent P11 re-review returned **Pass**; its
focused P11 suite passed 38 tests and direct regression selection passed 6.

The first combined C3 release review then found six integration gaps: a
cross-speaker house merge could erase speaker identity; a valid source-mode line
break could be rejected by an unrelated pre-existing QC failure; normal
history-off transcription did not retain its result for live-session editing;
the dialog exposed only line-break editing; serialized overlays could omit
schema/algorithm bindings; and status documents still described C3 as planned.
The repairs reject cross-speaker merges, compare new overlay blockers against the
baseline document, retain history-off results only in the live engine, expose
all five C3 edit controls with source/house eligibility, require explicit
serialized bindings, and update the operator documents to the delivered scope.
The renewed combined P13 review then returned **Pass** with no remaining
Critical, Major, or Minor findings. Its final edge-case probe also confirmed
that a merge spanning a known and unknown speaker assignment is rejected rather
than erasing the known identity.

## Verification evidence

### Automated regression

- `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ -q
  --ignore=tests/test_live_api.py --ignore=tests/test_live_audio_isolation.py`
  — **256 passed in 20.70 seconds**.
- Focused C3 overlay/lifecycle/UI/approval/export/CLI/CSV suite after the final
  repairs — **81 passed in 0.95 seconds**.
- `.venv/bin/python -m compileall -q elevenlabs_helper tests` — passed.
- `git diff --check` — passed.

The two live ElevenLabs API modules were intentionally excluded to avoid
external/billable calls.

### Wheel

- Built `elevenlabs_helper-0.2.0-py3-none-any.whl` with
  `.venv/bin/python -m build --wheel --no-isolation`.
- Installed its contents into an isolated `/tmp` target and imported them from
  `/private/tmp` using the project environment only for declared dependencies.
- Verified installed `CaptionOverlay`, `CaptionApproval`, overlay/approval load
  APIs, `cea608_repertoire_v1.json`, and the re-export
  `--caption-overlay`, timing, profile, and policy CLI controls.

### Frozen macOS application

- PyInstaller 6.21.0 built the arm64 app with Python 3.12.12 on arm64 macOS
  15.6.1.
- The bundle contains the pinned caption repertoire data.
- The frozen executable launched offscreen with an isolated data directory,
  stayed in its event loop, created `jobs.db` and its application log, emitted
  no traceback, and was terminated after the smoke window.

### Performance

Measured on an Apple M3 Max MacBook Pro with 64 GB memory, arm64 macOS 15.6.1,
and Python 3.12.12. The acceptance target is at most 30 seconds and 256 MiB peak
RSS delta for 10,000 tokens/60 minutes.

| Input | Result | Runtime | Peak RSS delta |
|---|---:|---:|---:|
| 5,000 tokens / 30 minutes | 417 events, pass | 12.538 s | 27.38 MiB |
| 10,000 tokens / 60 minutes | 834 events, pass | 25.381 s | 36.86 MiB |

The larger fixture used twice the tokens and duration and took about 2.02 times
as long.

## Claim boundary and remaining work

This gate covers the local C3 editorial workflow layered on the verified C1-C2
SRT/WebVTT authoring pipeline. Approval records are local workflow evidence, not
authenticated signatures or regulatory compliance records.

P12 now has separate C4 plans for exact frame alignment, shot context, named
destination overrides, generic TTML2, IMSC 1.3 Text, native CTA-608, and native
CTA-708. Those plans implement nothing by themselves. No native 608/708 bytes,
TTML/IMSC documents, frame/shot-aware output, named destination acceptance, or
player/carriage validation exists on this branch.

Manual validation with real ElevenLabs output and Dubbing Studio, native
destination decoder/player chains, distribution signing, and notarization remain
outside this non-live branch gate. No commit, push, merge, tag, publication,
live API call, or billable validation was performed.
