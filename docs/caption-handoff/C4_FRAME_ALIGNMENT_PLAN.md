# C4 frame alignment plan

Prepared and sources retrieved **2026-09-28**. F1 implementation verified
**2026-09-29**; see [C4 F1 verification](C4_F1_VERIFICATION.md). The exact core
is not wired to QC or exports, so current SRT/WebVTT output is not claimed to be
frame accurate and no native CEA, TTML, or IMSC exporter exists.

## Goal, scope, and standards evidence

Add an exact media-time-to-frame projection for a named C4 destination profile. It evaluates and, only where the profile allows, quantizes a house-timed `CaptionDocument` to a rational frame grid. A media timestamp, frame ordinal, and drop-frame timecode label are separate values and never substitute for one another.

It does not create 608/708 bytes, TTML/IMSC documents, styling, regions, placement, video probing, or source-word retiming. It remains text/timing-only. Native exporters are separate destination packets.

[W3C TTML2 sections 7.2.5--7.2.7](https://www.w3.org/TR/ttml2/#parameter-vocabulary-frameRate) are **normative**: they define frame rate and rational frame-rate multipliers. The [W3C DAPT profile timing section](https://www.w3.org/TR/dapt/#time-expression) is **normative** for DAPT and warns against clock time with frame components at non-integer rates. The authoritative SMPTE ST 12-1 text must be obtained from the [SMPTE Standards Library](https://pub.smpte.org/) before timecode-label support: it is **paywalled and unverified** here. SMPTE's public [time-code report page](https://www.smpte.org/standards/reports-downloads) is **informative** only.

## Contracts and precedence

Create `engine/captions/frame_time.py`; schema v2 reads beside current v1 rather than mutating stored floats:

```python
RationalTime(numerator: int, denominator: int)  # reduced; denominator > 0
CaptionFrameRate(numerator: int, denominator: int)  # exact fps
FrameGrid(frame_rate, origin_media_time=0/1,
          alignment="floor_start_ceil_end" | "none")
FrameProjection(event_id, start_frame, end_frame_exclusive,
                original_start, original_end, projected_start, projected_end,
                grid_hash, policy_id, policy_version)
TimecodeLabel(hours, minutes, seconds, frame, nominal_fps, drop_frame)
```

`CaptionContext` v2 adds `media_time_origin`, `frame_grid`, and optional `timecode_label_context`; v2 events add exact `start_time/end_time`. Legacy floats remain compatibility fields and are never silently promoted as exact values. `CaptionDocument.provenance` records grid/resolver/policy hashes and evaluation state; `CaptionQCReport` keeps coverage separate from technical status.

Precedence is explicit export option > exact named destination override > profile default > no projection. The requested grid must match numerator, denominator, and origin exactly. Source timing always resolves to `alignment="none"`: it is evaluated but never snapped, split, merged, extended, shortened, or converted in place.

## Exact rational algorithms

Parse a decimal lexeme as a rational (`"0.1" = 1/10`), never as binary float. Reduce every fraction with `gcd`; reject non-finite/unbounded values, non-positive denominators/rates, and `end <= start`. With frame rate `F = n/d`, origin `O`, and media time `T`, frame coordinate is `(T - O) * F`.

For the coverage-preserving house policy,
`start_frame = floor((Ts - O) * F)` and
`end_frame_exclusive = ceil((Te - O) * F)`. Require end greater than start;
projected bounds are `O + frame/F`. The algorithm can expand a caption interval
to the adjacent grid boundaries, then must re-run program, neighbor, gap,
duration, and overlap checks. It may never trim associated speech. If a named
destination requires nearest or contracting projection, report
`FRAME_ALIGNMENT_INCOMPATIBLE` unless a separate approved policy proves that the
specific endpoints do not cut speech or violate another rule. Keep the
projection separate from the semantic `CaptionDocument`. Conversion maps each
exact media endpoint to the target grid; it never scales a frame count. Ban
`round(time * fps)`, nominal decimal FPS, epsilon comparisons, accumulated
durations, and floats in identity material.

Timecode-label generation accepts only a non-negative integer frame ordinal, explicit nominal rate, and explicit drop-frame flag. Non-drop uses quotient/remainder. Drop-frame is enabled only for owner-approved mappings verified against licensed ST 12-1 clauses. Never apply a label's skip rule to media time or reconstruct media time from a label without grid/origin/mapping.

## QC, provenance, and determinism

Projection ID is `caption_frame_projection_` plus 24 SHA-256 hex digits of canonical sorted JSON: event ID, original fractions, grid, policy/version, document/profile hashes. Canonical JSON has integer numerator/denominator strings and excludes operational time.

Add `FRAME_GRID_UNKNOWN` (info), `FRAME_GRID_INVALID` (blocker), `FRAME_ALIGNMENT_INCOMPATIBLE` (failure for off-grid source timing), `FRAME_PROJECTION_EMPTY` (failure), `FRAME_RATE_CONVERSION_UNSUPPORTED` (blocker), `TIMECODE_LABEL_UNVERIFIED` (blocker), and `TIMECODE_LABEL_INVALID` (blocker). Source-mode incompatibility retains exact media times. Strict house output blocks on requested projection failure; draft may write only with measured sidecar findings. Malformed rational data, missing grid identity, and zero-frame projections are non-approvable.

## Verification, packaging, and rollout

Golden fixtures cover 24/1, 25/1, 30000/1001, 60000/1001, positive
and negative non-zero origins, boundary-neighbor times, one-frame events,
source-mode off-grid events, invalid input, and 24/1 to 24000/1001 conversion.
Expected values are fractions/ordinals. Property tests prove reduction
idempotence, speech-coverage preservation, stable ordering, deterministic
conversion, and no source mutation. The independent oracle is a test-only
`fractions.Fraction` implementation with no production imports; a second
reviewer checks approved drop-frame vectors against licensed SMPTE text. F2 and
F3 run `tests/test_dub_csv.py` and compare Manual-Dub bytes before and after
success, draft, blocked, and invalid-context paths. Each future exporter
separately needs syntax parser, independent converter round-trip, target-player
acceptance, and package evidence; an SRT conversion proves none of them.

`fractions` is standard library. Register module/profile data in `pyproject.toml` and PyInstaller if discovery requires it. V1 sidecars retain float behavior and report frame coverage unavailable. Roll out opt-in/profile-gated; support is only the verified grid/policy/exporter tuple.

| Packet | Owner/files | Dependency | Model tier | Hard checks |
|---|---|---|---|---|
| F1 | `models.py`, new `frame_time.py`, tests | C1--C3 | strong | no float identity; golden/property/oracle |
| F2 | `qc.py`, sidecars, tests | F1 | strong | source unsnapped; incompatible distinct from unknown; Manual-Dub byte invariant |
| F3 | one exporter/profile/tests | F1--F2 and primary evidence | strongest | parser, converter, player, package and Manual-Dub acceptance |

Owner decisions required: permitted grids and endpoint policy; whether event persistence migrates to rationals; licensed ST 12-1 edition/mappings; and first supported exporter/destination. The rulebook does not decide these.
