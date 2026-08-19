# ElevenLabs Helper — Project Handoff

*Last updated: 2026-07-20. Written for an engineer (or a future session) picking
this project up cold. Pair this with [ROADMAP.md](../ROADMAP.md) for forward work
and [DUBBING_WORKFLOW.md](DUBBING_WORKFLOW.md) for the dubbing strategy.*

---

## 1. What this is

A macOS desktop app that uploads audio to **ElevenLabs Speech-to-Text (Scribe)**,
runs a batch queue, and produces transcript deliverables (SRT / VTT / DOCX / JSON).
It is built as a **pure, headless engine** with a thin **PySide6 GUI** on top, so
the same core runs as a CLI or in a container for cloud workflows (e.g. SDVI Rally).

A second capability is in progress on a branch: **dubbing-workflow prep** —
speaker QC and a Manual-Dub CSV export that feed ElevenLabs Dubbing Studio for
English→Spanish dubbing.

**Current version:** `0.1.0` in [pyproject.toml](../pyproject.toml) (the working
tag line in commits/reviews is "v0.1.5" — the pyproject version was not bumped).

---

## 2. Repository status right now

| | |
|---|---|
| **Current branch** | `dubbing-workflow` (HEAD `ddd5e72`) |
| **Main branch** | `main` (HEAD `34da1f4`) |
| **Working tree** | clean (dubbing Phase 1 is committed on the branch, not yet merged) |
| **Tests** | 74 passing (`pytest`, excluding the opt-in live-API test) |
| **Not yet on main** | the entire dubbing-workflow feature (see §7) |

The `dubbing-workflow` branch is one commit ahead of `main`. Nothing is pushed to
a remote in this session — the repo has no configured GitHub remote for the branch.
Merging to main is a decision for the owner (see §9).

---

## 3. Architecture

```
elevenlabs_helper/
  engine/                    # PURE, UI-free core — importable anywhere
    config.py                #   limits, TranscriptionParams, EngineSettings, Deliverable enum, paths
    auth.py                  #   API key: explicit -> ELEVENLABS_API_KEY env -> macOS Keychain
    service.py               #   Engine facade (store + queue wiring; reexport; speaker edits)
    history.py               #   canonical transcript JSON kept in app-support dir (free re-export)
    edits.py                 #   NEW: speaker-rename/reassign overlay (<job_id>.edits.json)
    cli.py                   #   headless entry point (transcribe/inspect/history/reexport)
    media/inspect.py         #   size (stat) + duration (mutagen) + oversize warnings — no ffmpeg
    elevenlabs/
      client.py              #   Scribe HTTP client: streamed upload, retries/backoff, error types
      models.py              #   Pydantic response models (TranscriptionResult, Word)
    exporters/
      canonical.py           #   build_transcript(result) -> Transcript of Cues; apply_edits()
      srt.py / vtt.py / docx.py   # canonical -> deliverable renderers
      dub_csv.py             #   NEW: canonical -> ElevenLabs Manual-Dub CSV
      readability.py         #   NEW: subtitle re-timing transform (opt-in)
      writer.py              #   dispatch: write selected deliverables to disk
    jobs/
      models.py              #   Job + JobStatus
      store.py               #   SQLite persistence
      queue.py               #   single background worker; STAGED->Run flow; retry/cancel
    processors/
      base.py                #   Processor interface + ProcessContext
      speech_to_text.py      #   V1 feature: upload -> transcribe -> export (+ re-export fast path)
  desktop/                   # PySide6 GUI — thin shell over engine.service.Engine
    app.py                   #   QApplication bootstrap (gui entry point)
    bridge.py                #   EngineBridge: engine callbacks -> Qt signals
    reexport_action.py       #   shared re-export flow (format picker + overwrite guard)
    windows/
      main_window.py         #   drop area + job table + per-row actions
      history_dialog.py      #   browse/recover/permanently-delete past jobs
      speaker_qc_dialog.py   #   NEW: review/rename/reassign speakers before dubbing
    widgets/
      drop_area.py, job_options_dialog.py, key_dialog.py,
      settings_dialog.py, reexport_dialog.py
  packaging/                 # PyInstaller spec, build_dmg.sh, Dockerfile (engine+CLI only), main.py
  scripts/live_check.py      # manual live-API smoke test (reads key from Keychain/env, never prints)
  tests/                     # pytest suite (74 tests)
  docs/                      # DUBBING_WORKFLOW.md, HANDOFF.md (this file)
```

**The golden rule:** the GUI contains no business logic. Everything flows through
`engine.service.Engine`. If you find yourself writing logic in `desktop/`, it
probably belongs in the engine so the CLI/container gets it too.

**The extension seam:** `JobQueue(processor=...)` takes any `Processor`. New
ElevenLabs features (dubbing, etc.) are new `Processor` implementations — no queue
or GUI re-architecture required. This was a deliberate V1 design decision.

---

## 4. Core data flow

1. **Add** — a dropped/`add_source`'d file becomes a `Job` in status **STAGED**
   (persisted, *not* run). Size/duration are annotated up front; oversize files
   require acknowledgement.
2. **Run** — `run_staged()` promotes STAGED jobs to QUEUED and the worker picks
   them up one at a time (sequential by design). Nothing hits the API until Run —
   an accidental drop never spends credits.
3. **Process** — `SpeechToTextProcessor.run()`: validate → oversize gate →
   `transcribe_file()` (streamed, with retry/backoff) → save canonical JSON to
   history space → `write_deliverables()`.
4. **Persist** — the canonical `TranscriptionResult` JSON is kept in the
   app-support **history** dir (not the user's output folder), so deliverables can
   be regenerated **free** (no API) via `Engine.reexport()`.
5. **Recover** — archived jobs stay recoverable in the History dialog;
   `delete_permanently()` is the only path that discards the history JSON (and now
   the speaker-edits overlay).

**The canonical model is the single source of truth.** Every deliverable
(SRT/VTT/DOCX/JSON/dub-CSV) is rendered from `exporters.canonical.Transcript`.
A `Transcript` is a list of `Cue`s (start, end, text, speaker_id, is_audio_event),
split by speaker change / gap / length / sentence boundary in `build_transcript()`.

`JobStatus`: STAGED → QUEUED → UPLOADING → TRANSCRIBING → EXPORTING → DONE, with
FAILED / RETRYING / CANCELED as side states. Terminal = {DONE, FAILED, CANCELED}.

---

## 5. Key decisions & constraints (the "why", so you don't undo them)

- **V1 is `.mp3`-only, no conversion.** FFmpeg was deliberately removed from V1
  (pivot 2026-06-23). Duration is read with pure-Python `mutagen`. Video input +
  transcode is a roadmap item, to return behind the same `Processor`/media interface.
- **No OAuth exists for the ElevenLabs API** — API keys only. The key lives in the
  macOS Keychain (service `ElevenLabsHelper`, pinned to the secure backend);
  headless runs use `ELEVENLABS_API_KEY`. The key is never logged or printed.
- **Sequential queue, single worker.** Intentional for V1 (predictable spend,
  simpler cancel/retry). The `pause/resume` toggle was removed once STAGED existed.
- **Staged-then-Run.** Spending credits is always an explicit user action.
- **Streamed upload** from disk — large files are never loaded fully into memory.
- **Permanent vs transient failure** is classified at every step: permanent =
  missing file / invalid key / oversize-unacknowledged / 413 / output-write error;
  transient = 429 / 5xx / network (retried with backoff). Don't collapse these.
- **History JSON is separate from user output** so re-export survives the user
  deleting their files; retention is configurable (`history_retention_days`, 0 =
  forever) for data-minimization.
- **AI provenance** is disclosed in VTT (a `NOTE` line) and DOCX — keep it.

---

## 6. How to run, test, build

```bash
# One-time: create venv + install (dev + gui extras)
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,gui]"

# Tests (74; excludes the live-API test which needs a real key)
.venv/bin/python -m pytest tests/ -q --ignore=tests/test_live_api.py

# CLI (headless engine)
elevenlabs-helper transcribe clip.mp3 --out ./out --formats srt,vtt,dub_csv
elevenlabs-helper inspect clip.mp3
elevenlabs-helper history
elevenlabs-helper reexport <job-id-or-json> --formats srt,vtt

# GUI
elevenlabs-helper-gui          # or: python packaging/main.py

# Live API smoke test (needs a real key in Keychain/env; never prints the key)
.venv/bin/python scripts/live_check.py path/to/real.mp3

# Package the Mac app / dmg
bash packaging/build_dmg.sh     # uses packaging/elevenlabs_helper.spec (PyInstaller)
```

Dependencies are hash-pinned in `requirements.lock` (pip-compile). `pip-audit` is
a release gate. Python 3.12–3.13.

**GUI testing without a display:** set `QT_QPA_PLATFORM=offscreen` to construct and
drive dialogs headlessly (used to verify the Speaker QC dialog in this session).

---

## 7. What changed on the `dubbing-workflow` branch (Phase 1)

Goal: move dubbing *prep* upstream into this app so ElevenLabs Dubbing Studio
projects open with correct speakers/clips and cost fewer paid regenerations. The
team keeps the Studio as the editing surface (they want that editorial control).

**New engine pieces:**
- `engine/edits.py` — `SpeakerEdits` overlay (`speaker_names`, `cue_overrides`)
  persisted as `<job_id>.edits.json` beside the history JSON. The canonical result
  is never mutated; edits are applied at export time via
  `canonical.apply_edits(transcript, edits)`.
- `engine/exporters/dub_csv.py` — renders the ElevenLabs **Manual-Dub CSV**
  (`speaker,start_time,end_time,transcription,translation`). Dialogue-only,
  **waveform-aligned** timing, seconds timecodes (chosen over `HH:MM:SS,mmm` to
  avoid comma-quoting against a strict parser), empty translation column.
- `engine/exporters/readability.py` — `retime(transcript)` relaxes SRT/VTT display
  timing for reading comfort (min 1s, ≤17 chars/sec, merge tiny same-speaker
  fragments, ~2-frame gaps). Pure transform; input transcript untouched.
- `Deliverable.DUB_CSV` + `EngineSettings.readable_subtitles` flag.
- `Engine.get_transcript()`, `get_speaker_edits()`, `save_speaker_edits()`;
  `reexport()` and the processor now apply edits + optional readable re-timing.
  `delete_permanently()` also discards the overlay.

**New GUI pieces:**
- `desktop/windows/speaker_qc_dialog.py` — a finished job's **⋯ → Review
  speakers…** opens a cue table with per-cue speaker dropdowns + per-speaker
  rename fields. Save writes the overlay; re-export reflects it.
- `reexport_dialog.py` gained the DUB_CSV deliverable + a "Readable subtitle
  timing" checkbox.

**Tests added (20):** `test_dub_csv.py`, `test_speaker_edits.py`,
`test_readability.py`.

**Design invariant to preserve:** the **Dubbing CSV always keeps waveform-aligned
timing**; only SRT/VTT get the readable variant. Tests enforce this — don't break it.

---

## 8. Key facts about ElevenLabs dubbing (verified July 2026)

These drove the Phase 1 design; full detail in [DUBBING_WORKFLOW.md](DUBBING_WORKFLOW.md).

- Dubbing bills **per source-minute per target language**, whether or not you
  supply your own script/translation. Supplying them saves *setup time and paid
  regenerations*, **not credits**. (Subscription: ~5k credits/min Studio
  watermarked, ~10k clean. API: ~$0.50/min Studio.)
- **Manual Dub** (Studio web UI) accepts video + optional separate foreground/
  background audio + the CSV. The API's `mode=manual` is documented as
  experimental — use the web UI Manual Dub upload.
- Studio projects include a limited free-regeneration allowance; past it,
  regenerations bill against quota — so arriving with correct speakers/text pays off.

**Open item for the owner:** confirm whether the account bills dubbing via
subscription credits or API dollars — it changes the optimization math.

---

## 9. Suggested next steps

**Immediate / decisions:**
1. **Real-world validate the CSV**: upload a generated `.csv` + video via Dubbing
   Studio → Manual Dub and confirm the project opens with correct clips/speakers.
   This is the one thing not covered by automated tests (strict-parser behavior).
2. **Merge decision** for `dubbing-workflow` → `main` (owner's call). No GitHub
   remote is configured for pushing/PR in this repo state.
3. **Bump the pyproject version** if you cut a release (it still says `0.1.0`).

**Phase 2 (planned):** external EN→ES translation pass (Claude API or DeepL +
project glossary) that fills the CSV `translation` column, QC'd in-app before upload.

**Phase 3 (planned):** video input (FFmpeg module returns), optional local
**Demucs** stem separation (the team sometimes has real stems; when they don't,
produce a dialogue-only track + stereo bed), and possibly direct dubbing-API
project creation (`POST /v1/dubbing` + polling) rather than manual upload.

**Standing V1.x items** (from ROADMAP): DPA/data-rights evidence before regulated
use, deferred UX/eng minors, code-signing + notarization as a release gate.

---

## 10. Landmines & gotchas

- **Don't add business logic to `desktop/`** — it won't reach the CLI/container.
- **Don't mutate the canonical `TranscriptionResult`/`Transcript`** to reflect user
  edits — use the overlay (`engine/edits.py`). Re-export must stay free and repeatable.
- **Cue indices** in the speaker-edits overlay refer to `Cue.index` from
  `build_transcript()` — deterministic for a given stored result. If you ever
  change the cue-splitting heuristics in `canonical.py`, existing overlays for
  already-transcribed jobs could point at shifted cues. (Low-risk in practice; be
  aware.)
- **Oversize handling** is a two-part gate (warn + acknowledge). Both the GUI
  confirm and the CLI `--force` set `job.acknowledged_oversize`; the processor
  re-checks. Keep all three in sync.
- **The live-API test** (`tests/test_live_api.py`) is excluded by default and needs
  a real key — don't add it to CI without a key strategy.
- **Keychain access** can prompt on macOS; headless/CI must use the env var.
- `mutagen` reads headers only — duration can be `None` for odd files; the code
  treats unknown duration as "may exceed limits," not "fine."
