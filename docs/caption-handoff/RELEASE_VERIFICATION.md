# Caption C1-C2 Release Verification

> Historical C1-C2 gate. C3 overlays, approvals, and lifecycle behavior were
> subsequently delivered and are covered by
> [Caption C3 release verification](C3_RELEASE_VERIFICATION.md).

Verification date: 2026-09-24

Branch/worktree: `codex/caption-rulebook`, uncommitted and unpushed
Verdict: **Pass for the implemented C1-C2 feature-branch scope**

## Verified scope

- The universal 608/708/Web authoring rulebook governs the versioned house
  profile. Readability scoring chooses among candidates that already satisfy
  those constraints.
- Settings, per-job options, re-export, and CLI support `house` and `source`
  timing. **Keep ElevenLabs timing (SRT/VTT)** maps to `source`.
- Fresh settings default to `house`. Legacy `readable_subtitles=true` migrates
  to `house`; `false` or a missing legacy value migrates to `source`.
- Source mode preserves the source cue count and exact start/end timestamps
  while applying line authoring and QC. House mode authors segmentation, lines,
  and timing together under bounded deterministic search.
- SRT and VTT render from one immutable `CaptionDocument` and emit versioned
  `.caption-document.json` and `.caption-qc.json` sidecars.
- Draft exports label review requirements. Strict exports block caption
  replacement for failed technical QC or required editorial review.
- Caption QC is visible from current-job and history surfaces, with sidecar hash
  validation, recovery states, source ranges, findings, and free re-export.
- Dubbing CSV continues to use waveform/source timing and does not consume the
  caption interpretation layer.

## Independent review

The independent P13 review initially found four material issues. The branch was
repaired and re-reviewed:

1. House segmentation and timing were previously selected in separate stages.
   Composition now jointly scores segmentation, duration, CPS, overlap, and
   hang constraints in a bounded iterative dynamic program, including long
   close-gap blocks.
2. Editorial coverage previously reported no required reviews. Audio-event and
   multi-speaker identity uncertainty now emit source-linked approval-required
   findings; draft, strict, job status, and CLI behavior agree.
3. Documentation implied broader 608/C2 completion than the code established.
   Claims now distinguish rulebook-driven SRT/VTT authoring and pinned glyph
   repertoire membership from actual 608/708 encoding.
4. Distribution and performance evidence was incomplete. The checks below now
   cover the final code.

Final reviewer verdict: **Pass; no remaining release-blocking correctness issues
found.** Its final targeted suite passed 22 tests, the two-speaker counterexample
passed, and `git diff --check` passed.

## Verification evidence

### Automated regression

- `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ -q
  --ignore=tests/test_live_api.py --ignore=tests/test_live_audio_isolation.py`
  — **202 passed in 20.40 seconds**.
- `.venv/bin/python -m compileall -q elevenlabs_helper` — passed.
- `git diff --check` — passed.
- Focused caption QC/writer/CLI/export-path suite after the speaker-review repair
  — **30 passed**.

The two live ElevenLabs API modules were intentionally excluded to avoid
billable/external calls.

### Wheel

- Built `elevenlabs_helper-0.2.0-py3-none-any.whl` with `python -m build
  --wheel --no-isolation`.
- Installed the wheel without dependencies into an isolated `/tmp` target and
  imported it from `/private/tmp`, outside the checkout.
- Verified the installed resource
  `engine/captions/data/cea608_repertoire_v1.json` and parsed the
  `--caption-timing`, `--caption-profile`, and `--caption-policy` CLI options.

### Frozen macOS application

- PyInstaller 6.21.0 built the arm64 app successfully with Python 3.12.12 on
  macOS 15.6.1.
- Verified the pinned glyph-repertoire JSON inside the app resources.
- Launched the frozen executable with `QT_QPA_PLATFORM=offscreen` and an
  isolated `ELEVENLABS_HELPER_DATA_DIR`. It remained in the event loop during
  the smoke window, created `jobs.db` and its application log in that directory,
  emitted no traceback, and was then terminated by the test harness.

### Performance

Measured on an Apple M3 Max MacBook Pro with 64 GB memory, arm64 macOS 15.6.1,
and Python 3.12.12. The acceptance target was at most 30 seconds and 256 MiB peak
delta.

| Input | Result | Runtime | Peak memory delta |
|---|---:|---:|---:|
| 5,000 tokens / 30 minutes | 311 events, pass | 2.560 s | 17.39 MiB |
| 10,000 tokens / 60 minutes | 621 events, pass | 5.192 s | 26.30 MiB |

Runtime scaled by about 2.03 times when input size doubled.

## Claim boundary and remaining work

This gate verifies C1-C2 rulebook-driven authoring for SRT/VTT, structured QC,
configuration, re-export, CLI, UI visibility, and distribution packaging. The
pinned libcaption-derived data establishes CEA-608 repertoire membership only.

The following remain open:

- P10-P11 were delivered after this historical gate; see the C3 verification
  record linked above.
- P12/C4: real 608/708 encoding, destination-specific WebVTT/SRT/IMSC/TTML
  profiles, frame-rate conversion, and player/destination validation.
- Manual validation with real ElevenLabs output and Studio import.
- Native 608/708 decoder/player validation.
- Distribution signing and notarization.

No commit, push, merge, tag, publication, live API call, or billable validation
was performed as part of this gate.
