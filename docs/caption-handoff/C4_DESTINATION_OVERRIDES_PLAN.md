# C4 destination overrides plan

Prepared and sources retrieved **2026-09-28**. A destination override is an immutable named contract backed by primary specification evidence and exporter acceptance; it is never an arbitrary preset or a claim that house SRT/WebVTT works elsewhere.

## Goal, boundary, and primary evidence

Implement versioned named overrides that resolve on the 608/708/Web house profile and yield separately traceable export batches. They may tighten or add constraints only when the rationale points to exact primary evidence. They cannot weaken source integrity, content preservation, text/timing-only scope, or source-mode preservation.

[WebVTT, dated 20 May 2026](https://www.w3.org/TR/2026/CRD-webvtt1-20260520/)
is a W3C **Candidate Recommendation Draft** with normative syntax and processing
requirements, but it remains work in progress rather than a W3C Recommendation;
the dated snapshot must be pinned for a destination contract. [TTML2](https://www.w3.org/TR/ttml2/)
and [IMSC 1.3](https://www.w3.org/TR/ttml-imsc1.3/) are normative W3C
Recommendations for their formats/profiles. IMSC 1.2 is used only by a separately
named compatibility contract. [EBU Tech 3380 EBU-TT-D](https://tech.ebu.ch/docs/tech/tech3380.pdf)
is **normative** for EBU-TT-D, but its required layout/region information makes
it incompatible with current text/timing-only scope until an owner approves a
presentation policy. The official CTA catalogs currently make CTA-608 and
CTA-708 available at no charge, but native work remains **access/license-gated
and unverified** until a permitted revision-controlled copy and reviewed clause
map are present. SMPTE ST 12-1 remains access-gated/unverified here. Vendor
pages, converter behavior, and player tests are **informative** interoperability
evidence, not normative requirements.

## V2 models and exact resolution

Replace the loose v1 override only in schema v2; v1 sidecars read as unsupported legacy overrides:

```python
SpecReference(publisher, title, edition, url,
  status="normative"|"informative"|"paywalled"|"unverified",
  retrieved_on, sections, content_hash)
DestinationConstraint(key, value, source_refs)
CaptionDestinationOverrideV2(destination_id, version, display_name,
  output_format, constraints, primary_specs, verification_state,
  exporter_id, exporter_version, override_hash)
ResolvedDestinationProfile(house_profile_hash, override_hash,
  effective_constraints, resolution_trace)
CaptionExportBatch(batch_id, destination_id, destination_version,
  resolved_profile_hash, input_document_hash, context_hash,
  artifact_manifest_hash, disposition)
```

All enforced constraints require a direct primary reference unless state is `planned` or `blocked`. `retrieved_on` records evidence collection, not permanent freshness. `paywalled` blocks verified status; `unverified` means primary evidence is absent; `informative` never satisfies normative proof.

Choose exact `(destination_id, version)`, then explicit export timing/context, destination constraints, and house profile. Duplicate keys require defined operators: minimum for maxima, maximum for minima, equality for format/timebase, intersection for allowed sets. Empty intersection, unknown key, duplicate without an operator, or relaxed house invariant is a blocker. Never fall back to another version/name/format. One semantic document resolves to one independent batch per destination; a failure cannot overwrite, suppress, or re-label another batch.

## Source/house semantics, QC, identity

House mode may meet authorized destination frame/shot/duration requirements only through bounded authoring that preserves the content ledger. Source mode always retains its derived cue boundaries unchanged. A frame-snap/non-overlap requirement that source timing violates emits an incompatibility and blocks strict output; it cannot produce a destination-looking derivative by mutating timing. Overrides cannot add styles, regions, placement, colors, fonts, voice presentation, or content transforms. EBU-TT-D is blocked pending owner-approved scope work.

Add `DESTINATION_UNKNOWN`, `DESTINATION_VERSION_UNKNOWN`, `DESTINATION_SPEC_UNVERIFIED`, `DESTINATION_PRIMARY_SPEC_PAYWALLED`, `DESTINATION_CONSTRAINT_CONFLICT`, `DESTINATION_FORMAT_UNSUPPORTED`, `DESTINATION_TEXT_TIMING_SCOPE_VIOLATION`, `DESTINATION_SOURCE_TIMING_INCOMPATIBLE`, `DESTINATION_EXPORTER_UNVERIFIED`, `DESTINATION_CONVERTER_REJECTED`, and `DESTINATION_PLAYER_REJECTED`. Unknown/version/spec/paywall/conflict/format/scope are blockers. Source incompatibility is a failure blocking strict batch output. Converter/player rejection blocks verified status. Draft batches carry measured QC, resolved profile, and evidence state. Bad constraints, missing primary clauses, source integrity, and scope violations are non-approvable.

Hash canonical sorted JSON with exact rational strings. Override hash includes constraints, URL/edition/section/status/retrieval date, exporter identity, and verification state; excludes display prose/operational time. Batch ID binds input document, resolved profile, exporter version, destination identity, context/frame/shot hashes, and format. Artifact manifests list output paths and SHA-256 bytes. Same inputs repeat; distinct destinations remain distinct even when bytes match.

## Tests, acceptance, packaging, rollout

Each override has a golden semantic document, resolved profile, output, QC sidecar, and evidence manifest. Test precedence, intersections, stale/unknown versions, tightening, attempted relaxation, separate identical-content batches, unchanged source-mode fractions, globally unique planned artifact paths, and reproducible hashes. Property tests permute constraint order/equivalent fractions and prove resolution/hash stability; generated conflicts must fail order-independently. D2 and D3 run `tests/test_dub_csv.py` and compare Manual-Dub bytes before and after successful, draft, blocked, conflicting, and unsupported-destination requests. The independent oracle is a test-only serialized-constraint resolver with no production resolver imports.

For each exporter, acceptance requires a format validator where available, independently maintained parser/converter round-trip preserving permitted text/timing/IDs, named player/device playback with version and test-media manifest, and package proof. Encoded 608/708 additionally needs standards-aware decoder and transport/container inspection. A one-off downstream SRT conversion proves no native destination.

Store overrides in `engine/captions/destinations/`; register package data/PyInstaller. Keep converter/player binaries pinned optional test tools with version/license/checksum evidence, never hidden runtime dependencies. Legacy overrides remain explicitly unsupported. Roll out one feature-gated format/destination at a time; support only the exact published override/exporter/evidence tuple and deprecate versions explicitly.

| Packet | Owner/files | Dependency | Model tier | Hard checks |
|---|---|---|---|---|
| D1 | `models.py`, `profiles.py`, new `destinations/`, tests | C1--C3 | strong | canonical resolver/oracle/property; no fallback |
| D2 | `writer.py`, `qc.py`, sidecar tests | D1 | strong | independent paths/batches; source and Manual-Dub preservation |
| D3 | one renderer/profile/tests | D1--D2 and primary clauses | strongest | validator, parser, converter, player, package and Manual-Dub invariant |
| D4 | dedicated 608/708 encoder/decoder/container | D1--D2 and licensed CEA | strongest | bitstream and target-device acceptance |

Owner decisions required: first supported destination/player; whether EBU-TT-D presentation may exceed current scope; licensed CEA/SMPTE access; accepted validator/converter/player matrix; evidence retention; and per-destination draft-output permission.
