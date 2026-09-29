# C4 F1 exact frame-core verification

Verification date: 2026-09-29

Branch: `codex/caption-rulebook`

Verdict: **Pass for the isolated F1 exact-arithmetic and contract scope**

## Delivered scope

F1 adds strict, immutable exact-time contracts beside the existing v1 float
models and an isolated integer-arithmetic projection core. It supports reduced
rational media time, exact rational frame rates and origins, coverage-preserving
floor-start/ceil-end projection, evaluation-only source timing, deterministic
projection identities, explicit requested/effective grid provenance, and
bounded input validation.

Legacy caption events, contexts, documents, hashes, overlays, and approvals keep
their v1 identities. Exact events cannot be embedded in a v1 document; they are
supplied as separately validated enrichments bound to every v1 semantic field.
No float is promoted to an exact value.

## Review and repairs

The contract audit found v1 hash, exact-event binding, requested/effective grid,
legacy coverage, context-consistency, and bounded-input risks before release.
The first fresh review then found four remaining defects: runtime v2 events could
hide inside v1 documents, empty documents could report complete coverage, blank
v2 IDs did not link to v1 identities, and requested-grid provenance accepted an
unverified hash string. All four were repaired with regressions. The fresh
re-review returned **Pass** with no remaining Critical, Major, or Minor findings.

## Verification evidence

- Focused exact-frame/model suite: **37 passed**.
- Broader caption/Manual-Dub regression selection: **161 passed**.
- Full non-live suite: **286 passed in 20.73 seconds**; the two live ElevenLabs
  modules were excluded to avoid external or billable calls.
- `git diff --check` and `compileall` passed.
- The wheel built and was installed into an isolated target. Exact frame APIs
  imported from that target and produced the expected 24 fps golden projection.
- The arm64 PyInstaller app rebuilt, launched offscreen with isolated data,
  entered its event loop, created `jobs.db` and its log, and emitted no traceback.

## Claim boundary

F1 does not change current SRT/WebVTT timing or claim frame-accurate output. The
existing source, canonical, and timing pipeline stores floats, so it reports
exact coverage unavailable rather than inventing rational precision. F2 still
owns exact-source ingestion decisions, QC findings, sidecar provenance,
revalidation after projection, strict/draft disposition, and Manual-Dub
invariance through integrated paths. F3 and destination packets own exporter,
converter, player, carriage, and timecode-mapping acceptance.

No TTML/IMSC/native 608/native 708 encoder, drop-frame algorithm, shot context,
destination profile, live API validation, signing, notarization, or release
publication is delivered by F1.
