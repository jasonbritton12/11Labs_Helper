# ElevenLabs Helper

Upload media to **ElevenLabs Speech-to-Text (Scribe)** or **Voice Isolation**,
monitor a batch queue, and collect transcript or dialog-only deliverables. Ships as a
lightweight macOS desktop app over a **reusable, headless engine** that also runs
as a CLI/container for cloud supply-chain workflows (e.g. SDVI Rally).

**Transcription scope:** supply a ready-to-upload **`.mp3`** (no conversion).
**Voice Isolation Phase 1:** supply a **WAV, MP3, or MP4** and receive the native
ElevenLabs dialog-only response as `<source>_DX.<format>`. M&E creation, phase
inversion, alignment, and audio re-encoding are intentionally deferred.

## Architecture

```
elevenlabs_helper/
  engine/      # PURE, UI-free core — reuse anywhere (CLI, container, SDVI Rally)
    media/inspect.py   # size (stat) + duration (mutagen) + limit warnings — no ffmpeg
    elevenlabs/        # Scribe + Voice Isolation HTTP clients (streamed, retried)
    exporters/         # canonical transcript -> SRT/VTT/DOCX (+ raw JSON)
    processors/        # pluggable workflows: speech_to_text + voice_isolation
    jobs/              # Job model, SQLite store, sequential queue w/ retry
    cli.py             # headless entry point
    service.py         # Engine facade (store + queue wiring)
  desktop/     # PySide6 GUI — a thin shell that imports the engine
  packaging/   # PyInstaller spec, dmg build, Dockerfile
```

The GUI never contains business logic — it drives `engine.service.Engine`. The
same engine powers the CLI and the Docker image.

## Key behaviors

- **No conversion (V1):** the audio file is uploaded as-is, **streamed from disk**
  (never loaded fully into memory).
- **Dialog isolation:** select **Isolate dialog**, stage WAV/MP3/MP4 files, then
  press **Run**. Each native Voice Isolation response is streamed to
  `<source>_DX.<format>` and committed atomically so partial downloads are not
  exposed as completed output.
- **Feature-specific oversize gate:** before queueing, the file's size (via `stat`) and duration
  (via the pure-Python `mutagen` header reader) are checked against ElevenLabs'
  limits (transcription: 5 GB / ~10 h; Voice Isolation: 500 MB / 1 h). If either is exceeded you get a **warning that requires
  acknowledgement** (GUI confirm; CLI `--force`) before it's attempted.
- **Scribe defaults:** diarization, word timestamps, audio-event tagging, and
  auto-detect language all on (toggleable in Settings or per queued job).
- **Transcription deliverables:** SRT, VTT, DOCX; the raw JSON response is always kept as the
  canonical source of truth (`<stem>.raw.json`).
- **Staged, intentional runs:** dropped files are **staged** — nothing is
  transcribed until you press **Run**, so an accidental drop never spends credits.
  Files dropped while a batch runs also stage and wait for the next Run; an
  interrupted job re-stages on restart (never auto-runs).
- **Batch queue:** sequential processing, persistent history (SQLite),
  **auto-retry** of transient failures (429/5xx/network) with backoff.
- **Graceful failures:** every failure point is classified permanent (no retry:
  missing file, invalid key, oversize-unacknowledged, 413, output-write error) or
  transient (retried), each with human-readable status copy.
- **Output:** `…/<source-stem>/` next to each source (or a chosen root).

## Authentication

ElevenLabs has **no browser/OAuth login** for its API — only API keys. On first
run the app links to the ElevenLabs API-keys page and stores your pasted key in
the **macOS Keychain** (validated against the API on save). Headless/cloud runs
read `ELEVENLABS_API_KEY` instead.

**Suspected key compromise (rotation runbook):** revoke/rotate the key in the
**ElevenLabs dashboard → API keys**, then open **Settings → API Key** in the app
and paste the new key (it replaces the Keychain entry; the old one stops working
immediately once revoked upstream). For headless/CI, update the
`ELEVENLABS_API_KEY` secret. The app never logs the key.

## Data at rest & privacy

- Media you add is **uploaded to ElevenLabs** for transcription or dialog isolation (third-party AI
  vendor); it is processed under **ElevenLabs' own terms**. ElevenLabs is SOC 2
  Type II / ISO 27001 certified with a published DPA, but its strongest data
  controls (**no-training, Zero-Retention Mode, data residency**) are
  **Enterprise-only**. On non-Enterprise tiers (e.g. **Scale**), **enable the
  training opt-out** in your ElevenLabs account and assume uploads are retained up
  to ~3 years — treat the app as suited to **general/non-confidential** audio.
  See the DPA checklist in [ROADMAP.md](ROADMAP.md) before sending regulated content.
- Transcripts are **AI-generated and may contain errors** — verify before relying
  on them. DOCX deliverables carry an "AI-generated" disclosure line.
- **Deliverables** you choose (SRT/VTT/DOCX, optionally a JSON copy, or native
  dialog-only audio) are
  written **in cleartext** to your output folder (defaults: **SRT + VTT**). For
  sensitive content keep output on a **FileVault**-encrypted volume.
- **Transcript history:** the canonical JSON is also kept **silently in the app
  history space** (`~/Library/Application Support/ElevenLabsHelper/history/`),
  separate from your outputs, so you can **re-export deliverables for free (no API
  cost)** if you delete/move them. **Retention default: kept until you delete it**
  (Remove/Clear only hide from the list). For data-minimization, set **Settings →
  Auto-delete history after N days**, or turn off **Keep transcript history**
  entirely (zero local retention; disables re-export).
- **Re-export & recovery:** completed jobs have a **Re-export** button (pick which
  formats to regenerate — no API cost). **Remove**/**Clear completed** only *archive*
  a job (hide it from the list) — they **keep** the recovery copy. Use **History…**
  to search past transcripts, re-export, or **Delete permanently** (the only action
  that discards the recovery copy). CLI equivalents: `elevenlabs-helper history` and
  `elevenlabs-helper reexport <job-id-or-json> [--formats …]`.
- The app writes a redacted local audit log (`…/ElevenLabsHelper/logs/`) of job
  lifecycle + upload destination host — never the API key or transcript content.

## Develop / run

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[gui,dev]"
# Reproducible install (verifies hashes):
#   pip install --require-hashes -r requirements.lock
# Release check:
#   python -m pip_audit -r requirements.lock

# Desktop app
python -m elevenlabs_helper.desktop.app

# CLI
elevenlabs-helper inspect clip.mp3
ELEVENLABS_API_KEY=sk-... elevenlabs-helper transcribe clip.mp3 --out ./out --formats srt,vtt,docx
ELEVENLABS_API_KEY=sk-... elevenlabs-helper isolate interview.mp4 --out ./out
# add --force to proceed past size/duration limits

# Tests
pytest

# Live end-to-end check against the REAL Scribe API (spends credits; use a short clip).
# Reads the key from the Keychain or ELEVENLABS_API_KEY; never prints it.
python scripts/live_check.py path/to/clip_with_speech.mp3 --out ./out
```

> Use Python 3.12/3.13 (PySide6-supported). The engine alone (no `gui` extra)
> needs only Python — no system binaries.

## Build the Mac app (unsigned)

### Local build (current architecture)

```bash
pip install pyinstaller
./packaging/build_dmg.sh        # -> dist/ElevenLabs Helper.dmg (+ printed SHA-256)
```

Builds for the machine's own architecture (Apple Silicon on an M-series Mac,
Intel on an Intel Mac). A true `universal2` build (`TARGET_ARCH=universal2`)
requires universal2 wheels for every compiled dependency — notably
`pydantic-core` — which the default arm64/x86_64 wheels are not, so prefer
**per-arch builds** (below) over `universal2`.

### Both architectures via CI (recommended)

`.github/workflows/build-macos.yml` builds on **macos-14 (Apple Silicon)** and
**macos-13 (Intel)** native runners and produces `ElevenLabs-Helper-arm64.dmg` and
`ElevenLabs-Helper-x86_64.dmg` (each with a `.sha256`). It runs on a version tag
and attaches both to the GitHub Release:

```bash
git init && git add -A && git commit -m "ElevenLabs Helper v0.1.0"
git remote add origin git@github.com:<you>/<repo>.git && git push -u origin main
git tag v0.1.0 && git push origin v0.1.0      # triggers the dual-arch build
```

- **First launch (unsigned):** right-click the app → **Open** to clear Gatekeeper.
- **Sign + notarize later (optional):** `codesign --deep --options runtime --sign
  "Developer ID Application: …" "dist/ElevenLabs Helper.app"`, then `xcrun
  notarytool submit … --wait` and `xcrun stapler staple`.

## Cloud / SDVI Rally reuse

```bash
docker build -f packaging/Dockerfile -t elevenlabs-helper .
docker run --rm -e ELEVENLABS_API_KEY=sk-... \
    -v "$PWD/in:/in" -v "$PWD/out:/out" \
    elevenlabs-helper transcribe /in/clip.mp3 --out /out --formats srt,vtt,docx

# Voice Isolation (WAV / MP3 / MP4 -> native dialog-only audio)
docker run --rm -e ELEVENLABS_API_KEY=sk-... \
    -v "$PWD/in:/in" -v "$PWD/out:/out" \
    elevenlabs-helper isolate /in/interview.mp4 --out /out
```

The image is the engine + CLI (no GUI, no ffmpeg), so a Rally action can invoke
it directly.

## Roadmap

See **[ROADMAP.md](ROADMAP.md)** for the full plan: V1.1 review follow-ups (minor
eng/UX fixes), the **vendor data-rights / DPA checklist** (the one remaining
security gate, for regulated use), and V2 capability work below.

### Out of scope for V1

- **FFmpeg conversion module:** transcode/remux source media and support broader
  formats for transcription and post-processing. Voice Isolation Phase 1 uploads
  its supported WAV/MP3/MP4 inputs without conversion.
- **Derived M&E:** align and gain-match the isolated dialog against the source,
  invert it, and render a best-effort music-and-effects track at a controlled
  professional audio format.
- **Segmentation + stitching** of files beyond the API limits (transcribe in
  chunks, re-merge with corrected timecodes).
- **Higher-quality / lossless audio** options for dubbing-grade workflows.
- **Dubbing / Dubbing Studio** (a new `processors/dubbing.py` implementing the
  same `Processor` interface).
- Optional TXT/JSON/HTML/PDF user-facing exports (JSON already retained),
  webhook/async transcription, code-signing automation, Windows build.
```
