# C4 shot-context plan

Prepared and sources retrieved **2026-09-28**. This plan treats visual context as bounded evidence for QC; it does not turn inferred context into editorial truth.

## Goal, boundary, and standards evidence

Accept an explicitly supplied, provenance-bearing sequence of observed shot-transition times and check whether captions hang across a transition. House timing may consider an approved cut as a candidate only within its existing constraints. Source mode preserves cue count, order, start/end, and media times exactly; it reports incompatibility but never snaps, splits, merges, extends, or shortens a cue.

Never infer cuts from transcript pauses, speakers, punctuation, audio, thumbnails, or guessed FPS. No context means unknown; it is not a pass. This is text/timing-only: no video analysis, placement, style, or content invention.

[TTML2 timing](https://www.w3.org/TR/ttml2/#timing) is **normative** only for a future TTML destination and supports explicit timing context; it does not prescribe a house cut-hang threshold. [EBU-TT-D](https://tech.ebu.ch/docs/tech/tech3380.pdf) is **normative** for that format and shows distribution subtitles carry timing/presentation constraints; it does not define this app's policy. A detector, human log, or player observation is **informative** until the owner approves its source/tolerance. No paywalled rule is used here; destination-specific paywalled requirements stay **unverified** until their exporter packet retrieves them.

## Data model, provenance, and precedence

Add v2 context contracts, using the frame packet's exact `RationalTime`:

```python
ObservedShotChange(time, observation_id,
  source_kind="human_log"|"detector"|"conform_edl"|"other",
  logical_source_id, stable_source_key, confidence, observation_hash)
ShotContext(schema_version, observations: tuple[...] | None,
  media_time_origin, source_manifest_hash, observed_intervals)
ShotHangPolicy(policy_id, version, max_post_cut_hang,
  boundary_tolerance, allowed_source_kinds)
```

`CaptionContext` gains optional `shot_context`. Legacy `shot_change_secs` reads only through a marked `legacy_float` adapter; it is never silently treated as exact observed evidence. A document/report binds context hash, manifest hash, policy hash, accepted source kinds, coverage, and event-to-observation result. `logical_source_id` is a sanitized project-relative identifier, never an absolute path or URL. Raw local paths, signed URLs, query strings, credentials, and operator locators remain runtime-only and are excluded from persisted sidecars, logs, IDs, and hashes. `None` observations means unknown. `()` means the declared source saw no transitions within its declared intervals; it never claims no cuts in the program. Partial manifests must list inspected intervals.

Resolve explicit export context > job-captured context > unknown. Resolve policy as explicit destination override > named profile policy > disabled. A context is usable only if manifest, origin, rational timebase, and coverage agree with the media timeline. Any failure returns unknown coverage, not an invented empty set.

## Rational evaluation and house behavior

Use reduced rational comparisons. For shot `C`, event `[S,E)`, tolerance `t`, and max hang `H`:

- aligned when `abs(S-C) <= t` or `abs(E-C) <= t`;
- carried when `S+t < C < E-t`;
- post-cut hang is `E-C`, and fails only when it exceeds `H`;
- a cut outside declared coverage is not evaluated.

Use a two-pointer scan of ordered events/observations; do not perform all-pairs comparisons. A house search may split at `C` only when both successors satisfy source ledger, token boundaries, duration, CPS, following speech, frame grid, and destination constraints. It records observed-cut ID and decision. It cannot split an indivisible token, mis-handle speaker/content semantics, or convert unknown coverage into a pass. Presence of a cut is measurable evidence, not a mandatory re-authoring instruction.

## QC and deterministic identity

Derive observation IDs from the source-manifest hash, sanitized logical source
ID/stable key, source kind, and exact time, not list order. Define normalization
and length/character rules for the logical ID; reject values containing path
roots, URL schemes, query/fragment delimiters, control characters, or traversal.
Reject duplicate IDs/times without an explicit merge rule, invalid/non-finite or
unsorted values, origin/timebase mismatch, and ambiguous overlapping coverage.
Canonical sorted JSON/SHA-256 binds sanitized observations, policy, algorithm
version, and every event result.

Add `SHOT_CONTEXT_NOT_EVALUATED` (info), `SHOT_CONTEXT_PARTIAL` (info), `SHOT_CONTEXT_INVALID` (blocker), `SHOT_CONTEXT_TIMEBASE_MISMATCH` (blocker), `SHOT_CARRY_ACROSS_CUT` (warning), `SHOT_HANG_EXCEEDS_POLICY` (failure), `SHOT_ALIGNMENT_INCOMPATIBLE` (source-mode failure when required), and `SHOT_REAUTHORING_CONSTRAINED` (info). Actual/threshold fields use rational strings, cut IDs, coverage, and policy version. Bad evidence/unknown coverage/source integrity are non-approvable. A measured hang can use existing approvals only while preserving its finding and bound hashes.

## Tests, acceptance, rollout

Golden fixtures cover unknown; observed-empty; partial coverage; cut at start/end/tolerance edge; internal cut; exact/one-unit-over `H`; two cuts in one event; non-zero origin; source-mode preservation; cross-machine logical-ID determinism; and rejection/redaction of absolute paths, credential-bearing URLs, control characters, and traversal. Property tests prove order invariance, one evaluation per observation, no finding outside coverage, exact threshold equality, equivalent fraction determinism, and no source mutation. S2 through S4 run `tests/test_dub_csv.py` and compare Manual-Dub bytes before and after success, draft, blocked, invalid-context, and re-authoring-constrained paths. The independent oracle is a test-only `Fraction` interval classifier with no production imports; review compares fixtures/random vectors.

Shot QC alone cannot prove rendering. Every first destination exporter must show parser/converter and target-player preservation of the same immutable media manifest. Visual samples use that exact manifest and context evidence.

No dependency beyond standard-library `fractions` is expected. Register code/profile data if packaging needs it. Legacy floats report legacy/unknown precision. Roll out opt-in as QC-only first; support only captured source, coverage, policy, and verified exporter versions.

| Packet | Owner/files | Dependency | Model tier | Hard checks |
|---|---|---|---|---|
| S1 | `models.py`, new `shot_context.py`, tests | C1--C3/F1 | strong | unknown vs empty vs partial; oracle/property |
| S2 | `qc.py`, sidecars, tests | S1 | strong | no source mutation; approval binding; privacy and Manual-Dub invariants |
| S3 | `compose.py`, `timing.py`, tests | S1--S2, owner policy | strongest | every candidate obeys all timing/content/frame rules; Manual-Dub bytes unchanged |
| S4 | one exporter/profile/tests | S1--S3 | strongest | parser, converter, player, package acceptance |

Owner decisions required: trusted observation sources; `H`/`t` by destination; whether confidence is merely recorded or policy-bearing; operator presentation of partial coverage; and whether house re-authoring follows QC-only rollout.
