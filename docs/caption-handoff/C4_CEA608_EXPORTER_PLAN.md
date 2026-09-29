# C4 plan: native CTA-608 exporter

## Status and normative-access gate

This is planning only. It authorizes no encoder, package change, release, delivery, or conformance claim.

The normative reference is ANSI/CTA-608-E S-2019, Line 21 Data Services. CTA describes it as a technical standard/guide for captioning and other data services embedded in line 21 of the NTSC vertical blanking interval ([CTA catalog](https://shop.cta.tech/products/cta-608)). That catalog proves document identity, scope, and stabilized edition only. It cannot provide bytes, parity, control values, timing, or conformance rules.

Before implementation, an owner must obtain a permitted, revision-controlled copy of CTA-608 including applicable errata/interpretations, preserve its access/license record outside source control, and review a clause/table matrix for every encoder rule. Until this gate passes, all CTA-608 requirements below are blocked. Never infer them from libcaption, SCC tools, ffmpeg, third-party code, vendor guidance, sample streams, or decoder behavior. The current libcaption-derived glyph repertoire is C2 authoring screening only, not byte mapping or native-608 evidence.

No FCC rule is applied: the project has not selected a regulated workflow or made a regulatory claim. If an owner later selects one, legal/compliance review determines relevance; FCC rules do not substitute for CTA-608.

## Scope and non-goals

Build one deterministic encoder from an interpreted CaptionDocument to a named native-608 elementary representation and diagnostic manifest. It preserves authored wording, event identity, source linkage, and resolved options. It does not compose text, alter lines, identify speakers, re-run authoring, or change times.

The first profile supports one explicitly selected prerecorded delivery profile. It does not claim live captioning, complete Line 21 services, XDS/Text Mode, analog VBI insertion, downstream carriage/muxing, transcoding, receiver behavior, legal compliance, or general conformance. SRT/VTT, Manual-Dub CSV, canonical history, speaker overlays, approvals, and the text/timing-only authoring scope stay unchanged.

Native coding needs field/service/channel, mode, display-memory, row/column, and attributes. They are delivery defaults, not inferred placement. The exporter may not select them from text, speaker, timing, shot/image, or best-fit heuristics, and it may not add positioning/styling authoring UI.

## Dependencies and frozen interfaces

Require independently verified P10/P11 lifecycle behavior and renewed P13 before any support claim. Reuse without mutation:

- CaptionDocument: ordered CaptionEvents, authored lines, source ranges, deterministic hash, profile/options, and source or house timing mode.
- CaptionQCReport, approvals, and ExportResult: native findings add evidence but cannot erase authoring/editorial findings or convert an exception into compliance.
- CaptionContext.frame_rate: exact rational numerator/denominator if supplied; None is unknown, never assumed 29.97/30 fps.
- CaptionDocument is the only semantic input. Do not consume raw ElevenLabs words, canonical cue splitting, or full-text fallback.

After normative access, add a distinct immutable function boundary:

    encode_cea608(document, *, encoder_profile, context) -> NativeCaptionExport

NativeCaptionExport contains schema/encoder version; document/profile/defaults/clause-map and character-map hashes; ordered code units; per-event links; diagnostics; manifest/payload; and disposition (written, draft, blocked). The profile names CTA edition/errata, target representation, service/channel, timing basis, mapping version, and defaults version. Unknown identities fail closed. Do not overload the generic CaptionDestinationOverride.

Writer integration waits until core encoding and independent decoding pass. It plans/stages native payload/report before replacement and records only actual writes in ExportResult.paths. A blocked native request never overwrites SRT/VTT, history, overlays, or Manual-Dub CSV.

## Versioned defaults and owner decisions

Introduce immutable Cea608EncoderDefaults with defaults_id and version. It declares every delivery choice: field/service/channel, caption mode, display-memory policy, clear/end policy, row/column policy, required attributes, timing/scheduling basis, and artifact/transport representation. Permitted values and numeric coding come only from the licensed clause map.

There is no production default in this plan. A native request with no owner-approved version blocks as CEA608_ENCODER_DEFAULTS_UNRESOLVED. Fixtures may use named test defaults only. The owner must decide:

1. Target representation and downstream insertion owner: documented native schedule or named VBI/broadcast integration.
2. One initial field/service/channel and whether additional services are in scope.
3. Mode/display-memory lifecycle, including clear/end transitions.
4. Required row/column/attribute defaults. These remain transparent delivery defaults, not inferred positioning intent.
5. Language and licensed character-map scope, and policy for unsupported content.
6. Support boundary: raw native schedule only, or a named accepted delivery chain.

## Core encoder after the gate

### Fields, controls, timing, capacity

Implement licensed requirements as declarative, versioned data for character sets, parity/packing, controls, field/channel association, display memory, mode transitions, required control sequencing, and rate/capacity rules. Every generated pair has category (text, control, preamble, attribute, padding) and origin event/defaults policy; no unexplained numeric literal is allowed.

A pure scheduler calculates code-unit budget, mandatory overhead, transmission opportunities, display/clear deadlines, and final state from document timing and profile. It reports capacity exhaustion, impossible mode changes, missing timing basis, and invalid final state. It must not delete words, collapse lines, substitute characters, reorder events, delay speech for capacity, or borrow later capacity unless a reviewed normative rule allows it.

Source mode is strict: semantic count/order/numeric start/end remain exact. If a selected representation/grid cannot schedule a boundary faithfully, block payload with SOURCE_DESTINATION_TIMING_INCOMPATIBLE and identify the event/boundary. Do not snap, extend, shorten, split, merge, or round source timing. House frame alignment is a separate C4 capability; consume only a profile timing basis already validated for it.

Use integer or exact-rational time internally. Floating point serialization, wall clock, map iteration, path, or locale must not change bytes. Empty-document initialization/finalization is a clause-map/defaults decision, never guessed receiver behavior.

### Character mapping and unsupported data

Map each Unicode scalar and approved authored line break through a licensed, versioned CTA-608 map with clause/table source and redistribution status. Existing glyph lookup may be a preflight optimization only; it cannot select bytes.

For an unmapped scalar, combining sequence, newline/control character, or layout, preserve the document and report source-linked CEA608_UNMAPPABLE_CHARACTER or CEA608_LAYOUT_UNREPRESENTABLE. Block native payload. There is no normalization, transliteration, replacement glyph, drop, or best-effort fallback. A diagnostic manifest may be written only if it says no native payload exists.

### Serialization and artifact boundary

Use canonical JSON for profile/defaults/manifest and a separately versioned binary serializer for code units. Manifest includes schema, encoder, CTA edition/errata, profile/defaults/clause-map/mapping hashes, document/context hashes, timing basis, event-to-code-unit ranges, disposition, and diagnostics. Exclude generated time, absolute paths, credentials, and machine-specific data from hashes.

Do not call output SCC, VBI, 608, or broadcast-ready until an owner selects that representation. Initial development uses clearly internal names such as cea608 schedule JSON plus a versioned byte payload. A VBI/mux adapter is later work.

## Packets and file ownership

1. 608-N0 evidence: obtain CTA-608, record clause/table matrix, redistribution decision, target chain, and support boundary. No code.
2. 608-N1 contracts/defaults: new engine/captions/cea608_models.py and cea608_profiles.py with focused tests. Define strict versions and absent-default blocking.
3. 608-N2 mapping/state encoder: cea608_mapping.py and cea608_encoder.py, permitted generated data, tests. One selected service/mode; no writer changes.
4. 608-N3 scheduler/serializer: cea608_schedule.py and cea608_serialize.py, golden payload fixtures, independent-decoder tests.
5. 608-N4 integration: minimal writer adapter, package/spec inclusions, explicit CLI/UI only after owner approval, output-path tests. Coordinate before shared writer.py edits.
6. 608-N5 acceptance: operator runbook/evidence, selected inserter/mux and receiver/broadcast-chain tests, then renewed P13.

## Tests and acceptance

After 608-N0, create goldens for character-set edges; parity/packing boundaries; selected control/mode transitions; clear/end state; service/channel isolation; exact capacity and one unit over; rapid/overlapping events; empty document; invalid context/defaults; repeated encoding; source-mode off-grid/over-capacity rejection; unmappable/combining text; and corrupt payloads.

Every fixture asserts:

- Same document/profile/defaults/context gives byte-identical payload and canonical-identical manifest across processes.
- Code-unit categories and event ranges reconcile every encoded character/control; no unlinked bytes.
- An independent decoder, separately selected and qualified against licensed CTA-608, recovers expected service, text, state transitions, and schedule. Encoder code, shared mapping data, and libcaption are never the oracle.
- Altered/malformed bytes are rejected by independent validation; permissive parsing cannot hide errors.
- Source-mode semantic timing/count/order is identical, and Manual-Dub CSV remains byte-identical after native attempts.

Final acceptance requires an owner-selected inserter/mux and representative receiver/decoder chain. Retain capture artifacts, versions/configuration, field/service/channel, visual text/state verification, and timing evidence in an operator-controlled bundle. A conversion, library test, or player screenshot alone does not prove native-608 support.

## Packaging, support statement, release gate

Package only reviewed modules, profile/defaults schemas, redistributable mapping data, tests, and required attribution. Add explicit setuptools/PyInstaller inclusions; install-test the wheel without checkout on PYTHONPATH and test the packaged macOS app. Do not package CTA text or private broadcast captures without permission.

Until 608-N0 through 608-N5 pass: **The application does not export native CTA-608.** Afterwards state only verified CTA edition/errata, artifact representation, service/channel/defaults version, character scope, and independently accepted delivery chain. Do not claim CTA-608 compliance, broadcast readiness, or broad service support without separate owner-approved conformance evidence.
