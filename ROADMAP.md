# Roadmap

Tracks work intentionally deferred out of V1. V1 (single-`.mp3` → ElevenLabs
Scribe → SRT/VTT/DOCX) is built, and the current feature branch passes 96 tests
with two billable live checks skipped by default. Items below are grouped by
milestone.

---

## Next up

### Voice Isolation utility — IMPLEMENTED, EXPERIMENTAL / DE-PRIORITIZED

Adds a secondary engine workflow for ElevenLabs Voice Isolation. It remains
available through **Tools → Voice Isolation (Experimental)…** and
`elevenlabs-helper isolate`, but is no longer presented as a peer to the main
transcription workflow. WAV, MP3, and MP4 sources are uploaded as-is only after
the existing explicit **Run** action. The native response is streamed atomically
to `<source>_DX.<format>`. The workflow uses the documented 500 MB / one-hour
gate and shares the existing authentication/retry/cancel behavior.

The output is explicitly described as an AI-isolated dialog reference, not a
phase-coherent production DX stem. It does not promise a particular response
codec, sample rate, or channel layout.

### Explicit "Run" — stage jobs instead of auto-running on drop — ✅ SHIPPED (v0.1.5)
Implemented with a distinct **`STAGED`** job state (cleaner than the pause toggle:
*every* drop stages, including files dropped mid-run). A global **Run** button
promotes all staged jobs; interrupted jobs re-stage on restart (never auto-run).
Original problem/notes kept below for reference.

**Problem:** dropping a file currently enqueues it and the worker starts it
immediately, which spends money + bandwidth. An accidental drop shouldn't cost
credits.

**Change:** dropped files should be **staged** (added in a not-yet-started state),
and processing begins only when the user takes an intentional action — a **"Run"**
button (or e.g. "Transcribe" / "Start" if a clearer verb fits). Nothing hits the
API until the user says so.

**Design notes / considerations:**
- New job state before processing (e.g. `STAGED`/`READY`) distinct from `QUEUED`,
  or reuse the existing queue with a **default-paused** posture so staged files
  wait until "Run." (The pause-queue plumbing from S1.8 is a good starting point —
  this would make "hold until Run" the default rather than an opt-in toggle.)
- "Run" could be **global** ("Run all staged") and/or **per-row** ("Run this one");
  decide during design. Per-row lets users cherry-pick; global is faster for batches.
- Staged rows should still allow **Options** editing and **Remove** before running.
- Preserve add-while-running: files dropped during a run stage silently and wait
  for the next Run (don't auto-join the active batch unless the user chooses).
- Update the oversize-acknowledgement flow so it still fires before a staged job
  runs (or at stage time).
- Reflect this in the CLI too (transcribe is already explicit; ensure parity of
  mental model).
- Tests: dropped file stays non-running until Run; Run starts it; Remove a staged
  job never calls the API.

**Why:** intentional spend — the top request after v0.1.4.

## Evaluated and retired

### M&E through Voice Isolation phase subtraction — NOT PLANNED

User acceptance confirmed that the isolation endpoint can produce a useful
dialog-only reference, but its output is not sample- and phase-identical to the
dialog contribution in the source mix. Inverting or subtracting it therefore
leaves dialog residue and damages music/effects; further alignment cannot make
the processed signal reliably null.

For delivery-grade M&E, obtain original stems or an official M&E. A future
approximate workflow could evaluate dedicated source separation plus manual
reconstruction and listening QC, but that is a different capability and must not
be represented as recovered production stems.

### Universal caption interpretation layer — PLANNED

Use the house standard in
[Universal Caption Authoring Rule — 608 / 708 / Web](docs/universal-caption-authoring-rule_608-708-web.md)
as the default policy for prerecorded English readable-caption outputs. The
current `readability.retime()` behavior is a Phase-1 timing baseline, not the
finished authoring system.

Add an engine-level interpretation layer between the edited canonical transcript
and the SRT/VTT renderers. It will create one versioned semantic caption document
with explicit line breaks, resolved timing, source traceability, and structured
QC. Delivery renderers will consume that document rather than independently
reflowing text. Destination-specific profiles may override the house defaults.
Caption positioning and styling are out of scope: outputs must not emit placement,
alignment, font, color, size, or other presentation directives.

The implementation is split into four checkpoints:

1. **C1 — foundation:** versioned profiles, destination overrides, interpreted
   caption/QC models, and backward-compatible mapping from
   `readable_subtitles=True` to the house profile.
2. **C2 — deterministic rules:** 32 characters × 2 lines, natural line breaks,
   17/20 CPS target-warning-failure bands, 1–7 second durations, no overlap,
   speaker-change handling, glyph validation, and machine-readable QC.
3. **C3 — editorial review:** preview/QC UI, source-linked findings, manual
   split/merge/line-break controls, and separately persisted exception approvals.
4. **C4 — delivery context:** frame/shot-aware timing and verified 608, 708,
   WebVTT, SRT, IMSC, and TTML profiles as exporters land, all without emitted
   caption styling or positioning.

The canonical transcription and speaker edits remain immutable. The Dubbing CSV
continues to bypass caption interpretation and preserve waveform-aligned timing.
If the rules cannot be satisfied without changing meaning or synchronization,
the layer must emit a visible failure/approval requirement rather than truncate,
paraphrase, drop glyphs, or silently claim compliance.

Detailed architecture, rule mapping, verification matrix, and exit criteria:
[Caption Interpretation Layer Plan](docs/CAPTION_INTERPRETATION_LAYER.md).

---

## V1.1 — Review follow-ups (deferred minors)

Small, low-risk items from the third review round. None block V1 use.

> **Status (2026-06-29): code/UX minors DONE** — N1, N2, N3, UX-N1, UX-N2, UX-N3,
> UX-N4 are implemented and tested (41 tests pass). The only item still open is the
> non-code **vendor data-rights / DPA checklist** below.

### Engineering micro-fixes (review item "a") — ✅ done
- **N1 — Clear busy-state dicts on table rebuild.** `_busy_since`/`_busy_base`
  aren't cleared in `MainWindow._reload_table`; a job removed while in a busy
  status leaves stale entries (no crash — `_tick_elapsed` guards on `_rows`).
  Fix: add `self._busy_since.clear(); self._busy_base.clear()` in `_reload_table`.
  File: `elevenlabs_helper/desktop/windows/main_window.py`.
- **N2 — `validate_key` should return, not raise, on an insecure URL.**
  `_require_secure` raises `ElevenLabsApiError`, but `validate_key` otherwise
  returns `(status, message)`. Wrap the call and return `("invalid", str(exc))`;
  update `test_https_required_for_validate_key` accordingly.
  File: `elevenlabs_helper/engine/elevenlabs/client.py`.
- **N3 (optional) — Prune `_last_logged`** in `JobQueue` on terminal status to
  bound the dict over very long sessions. File: `elevenlabs_helper/engine/jobs/queue.py`.

### UX nitpicks
- **UX-N1 — Pause discoverability.** Per-job Options are reachable only if the
  user presses **Pause** before dropping a single file. Add a drop-zone hint
  ("Pause to set per-file options") or a "Hold new jobs" preference.
- **UX-N2 — Oversize dialog unknown-duration.** The row shows "duration unknown",
  but the oversize confirmation dialog doesn't mention it. Add a line when
  duration is `None`.
- **UX-N3 — AI marker on SRT/VTT.** DOCX carries "Generated by ElevenLabs Scribe
  (AI)"; add an equivalent leading `NOTE`/comment to SRT/VTT for provenance.
- **UX-N4 — Amber contrast.** Verify the `#b8860b` "no speech detected" color
  meets WCAG 1.4.3 in light/dark (meaning is also carried by text, so not
  blocking).

### Security / compliance (review item "b") — the remaining gate
- **Evidence the ElevenLabs vendor data-rights posture** before using the app for
  **regulated/confidential** content. This is the one item keeping the security
  gate at "Request Security Changes"; it is *not* a code change. See the
  **Vendor data-rights / DPA checklist** at the bottom of this file.
- **SRT/VTT AI disclosure** (same as UX-N3) supports AIUC Global disclosure for
  redistributed deliverables.
- **Key-rotation runbook** (1 paragraph in README): suspected key compromise →
  revoke/rotate in the ElevenLabs dashboard → update via Settings (Keychain).
  — ✅ done (README → Authentication).

---

## V2 — Capability expansion

The original "throw any file at it" vision, plus more ElevenLabs features.

- **FFmpeg conversion module:** accept MOV/MP4/WAV/etc.; transcode to a compact
  upload audio; show estimated size/duration. (Re-introduces the engine that was
  removed for V1 — keep it behind the same `Processor`/media interface.)
- **Segmentation + stitching:** split sources beyond the API limits (5 GB / ~10 h)
  into chunks, transcribe each, and re-merge with corrected SRT/VTT time offsets.
  (Note: `TranscriptionResult.offset()` already exists for this.)
- **Higher-quality / lossless audio** options for dubbing-grade workflows.
- **Dubbing / Dubbing Studio:** a new `processors/dubbing.py` implementing the
  same `Processor` interface (no queue/UI re-architecture needed). Strategy and
  phased plan in [docs/DUBBING_WORKFLOW.md](docs/DUBBING_WORKFLOW.md); Phase 1
  (speaker QC + Manual-Dub CSV + readable-subtitle re-timing) shipped on the
  `dubbing-workflow` branch.
- **Caption interpretation:** replace timing-only readable subtitles with the
  rulebook-driven, profile-based authoring layer described above. Maintain one
  semantic caption master for all delivery renderers.
- **More exports:** optional TXT / JSON / HTML / PDF as user-facing downloads
  (raw JSON is already retained internally).
- **Async/webhook transcription** for very long jobs (needs a callback endpoint;
  not viable for a pure desktop app without a relay).
- **Distribution:** code-signing + notarization automation as a release gate;
  optional Windows build (PySide6 is cross-platform; engine is pure Python).

---

## Vendor data-rights / DPA checklist (security gate for regulated use)

**Current plan: `Scale` (non-Enterprise).** That materially changes the answers:
the strong controls (no-training, Zero-Retention Mode, data residency) are
**Enterprise-only**, so on Scale they do **not** apply. Practical consequences:
- **Action required:** enable the **training opt-out** in your ElevenLabs account
  (Settings → Privacy) — on non-Enterprise tiers audio may otherwise be used to
  improve their models. Opt-out is prospective only.
- **No Zero-Retention Mode / no data residency** on Scale; assume uploads are
  retained up to ~3 years and processed in ElevenLabs' default region.
- **Recommendation:** treat this app as **fine for general/non-confidential audio**
  on Scale; for **regulated/confidential** content, upgrade to Enterprise (ZRM +
  residency + no-training + signed DPA) or don't send it.

Pre-filled from ElevenLabs' **public** docs (2026-07; verify against your own
account/tier + a signed DPA before relying on it for regulated content). ⚠️ = you
must confirm for your plan.

| # | Question | Public answer (verify) | Source |
|---|---|---|---|
| 1 | Audio **used to train** models? Opt-out? | **Enterprise: no** (not trained on beyond providing the service). **Non-Enterprise (Free/Creator/Pro/Scale): audio MAY be used to improve models unless you opt out** — opt-out is *prospective only*. ⚠️ **If you're not Enterprise, toggle the training opt-out in account settings.** | privacy-policy |
| 2 | **Retention** of audio + transcripts | Voice-generated data kept ≤ **3 years** after last interaction (or less); STT logging governed by request settings. **Zero-Retention Mode** deletes request/response data immediately — but **Enterprise-only**, and this app doesn't set it. ⚠️ | privacy-policy, ZRM docs |
| 3 | **Deletion** of uploaded content | Personal-data deletion via DSR/privacy process; ZRM = immediate. ⚠️ confirm process/SLA. | privacy-policy |
| 4 | **Sub-processors & data residency** | Regional residency **US / EU / India** — **Enterprise-only**. Sub-processor list on request. ⚠️ | data-residency |
| 5 | **DPA available?** | **Yes** — standard DPA published. ✅ (sign it for regulated use). | dpa |
| 6 | **Security posture** | **SOC 2 Type II, ISO 27001, PCI DSS L1**; HIPAA + GDPR attestations. ✅ | Trust Center |
| 7 | **Confidentiality / non-use** | Enterprise terms: customer content not used beyond providing the service. ⚠️ non-Enterprise differs (see #1). | privacy-policy / enterprise terms |
| 8 | **Breach notification** | Covered in the DPA (standard commitment). ⚠️ confirm timeline in signed DPA. | dpa |

**Bottom line:** For **regulated/confidential** audio, ElevenLabs is credible
(SOC 2 II / ISO 27001 / DPA / GDPR), **but the strong data-protection posture
(no-training, zero-retention, data residency) is largely ENTERPRISE-gated.** On a
non-Enterprise tier you should, at minimum, **enable the training opt-out** and
treat uploads as retained up to ~3 years. Sources: [Privacy Policy](https://elevenlabs.io/privacy-policy),
[DPA](https://elevenlabs.io/dpa), [Data residency](https://elevenlabs.io/docs/overview/administration/data-residency),
[Zero-Retention Mode](https://elevenlabs.io/docs/eleven-api/resources/zero-retention-mode),
[Trust Center](https://compliance.elevenlabs.io/).

Outcome: link the confirmed answers in README "Data at rest & privacy" and the
security gate clears for your tier; otherwise restrict to non-regulated content.
