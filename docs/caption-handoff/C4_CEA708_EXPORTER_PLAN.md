# C4 plan: native CTA-708 exporter

## Status and normative-access gate

This is planning only. It authorizes no encoder, package change, release, delivery, or conformance claim. Native 708 is independent of 608: 608 export, glyph lookup, or SRT/WebVTT conversion is not 708 evidence.

The normative reference is ANSI/CTA-708-E S-2023 & Errata, Digital Television (DTV) Closed Captioning. CTA says it defines coding for captions in digital television signals, including parameters that let users control caption appearance, and that the 2023 erratum is appended ([CTA catalog](https://shop.cta.tech/products/cta-708)). That catalog proves identity, scope, edition, and erratum only. It cannot yield packet syntax, service blocks, controls, window rules, character mappings, timing, or conformance tests.

Before implementation, an owner must obtain a permitted copy of this exact edition/erratum, preserve access/license information outside source control, and prepare a reviewed clause/table matrix for every encoder rule. Until this gate passes, all CTA-708 requirements are blocked. Do not infer them from libraries, decoder code, sample streams, vendor documents, or 608 behavior. Platform/vendor manuals may later be retained only as labeled non-normative interoperability evidence; they cannot override the clause map or be compliance oracle.

No FCC rule is applied: no regulated distribution or legal claim has been selected. A future delivery owner may request legal review for a chosen chain; it is separate from CTA-708 coding.

## Scope and non-goals

Build one deterministic encoder from a fully interpreted CaptionDocument to a named native-708 elementary representation and diagnostic manifest. It consumes authored text/timing/source linkage and emits scheduled DTVCC units. It never re-segments, rewrites text, derives position from image/speaker data, styles authored text, or mutates canonical history, overlays, approvals, or Manual-Dub CSV.

The first profile supports one owner-selected prerecorded service and transport representation. It excludes automatic 608 fallback, multiple services, arbitrary window styling, live ingest, multiplex insertion, video/container authoring, receiver UX, legal compliance, and universal conformance. A later carriage/mux adapter and each extra service are new profiles with their own fixtures and acceptance.

CTA describes 708 appearance parameters. This app remains text/timing-only at authoring. Native syntax may require window, pen, anchor, row/column, and mode values; use only owner-approved, versioned delivery defaults. Never infer visual intent from captions or scene data and never add styling controls to authoring UI.

## Dependencies and frozen interfaces

Require independently verified P10/P11 lifecycle behavior and renewed P13 before a support claim. Reuse without mutation:

- CaptionDocument is the semantic master: ordered CaptionEvents, authored lines, source ranges, deterministic hash, profile/options, source/house timing mode.
- CaptionQCReport, approvals, and ExportResult retain existing evidence. Native findings add detail; no authoring/editorial failure disappears.
- CaptionContext.frame_rate is exact rational data when supplied; missing frame/shot data stays unknown.
- Current 608 glyph screening and CaptionDestinationOverride cannot represent 708 packet, service, or window semantics and are not native evidence.

After normative access, add a distinct immutable boundary:

    encode_cea708(document, *, encoder_profile, context) -> NativeCaptionExport

The result includes schema/encoder version, document/profile/defaults/clause-map/character-map hashes, ordered DTVCC packet/service-block schedule, event links, diagnostics, manifest/payload, and disposition. Encoder profile names CTA edition/errata, target representation, service, packetization, timing basis, mapping version, and defaults version. Unknown/mismatched identities fail closed. Do not share native state with the 608 encoder.

Writer integration waits for core bytes and independent decoding. Plan/stage native payload/report before replacement, add only actual paths to ExportResult.paths, and preserve SRT/VTT when native export blocks. Payload includes document hash to prevent stale validation claims.

## Versioned defaults and owner decisions

Add immutable Cea708EncoderDefaults with reviewed ID/version. It declares target representation/carriage boundary; packet and sequence policy; service number; service-block policy; window lifecycle and active-window policy; compulsory window/pen attributes; compulsory row/column/anchor/print-direction defaults; clear/delete/reset behavior; timing basis; padding/capacity policy. Permitted values and numeric forms come only from licensed clause map.

There is no implicit production default. A native request with no owner-approved defaults blocks as CEA708_ENCODER_DEFAULTS_UNRESOLVED. Fixtures use named test defaults only. The owner must decide:

1. Native artifact and operational owner: documented packet schedule or named carriage/mux contract.
2. Initial service/language scope, language metadata validation, and additional-service product scope.
3. Window lifecycle, reset/clear sequence, and compulsory attributes/anchors/row/column/pen defaults. These are delivery defaults, not inferred placement.
4. Packet timing basis, frame/cadence assumptions, payload/rate budget, and unschedulable-document behavior.
5. Licensed character-map scope and policy for unmappable content/layout.
6. Support boundary: raw schedule only, or a named accepted carriage/receiver chain.

## Core encoder after the gate

### Packets, services, controls, timing, capacity

Implement audited declarative CTA-708 data for headers, sequence behavior, service blocks, extension/control paths, text code sets, window/pen/location commands, reset/clear/display actions, padding, and rate/capacity limits. Each unit has typed source-linked operation (header, service block, text, window, pen, control, padding); numeric values resolve through reviewed map.

The pure scheduler creates packet/service-block order from event timing/defaults. It measures packet/service capacity, mandatory overhead, sequence continuity, transmission opportunities, display deadlines, and final state. It reports overflow, oversized block, invalid sequence transition, missing defaults, unavailable grid, missed display transition, and incompatible final state. It must not omit text, substitute glyphs, invent windows, use another service, reorder events, or defer speech for packet budget.

Source mode retains semantic count/order/numeric start/end exactly. If selected representation cannot carry a boundary faithfully, report SOURCE_DESTINATION_TIMING_INCOMPATIBLE with event/value and block payload. Do not frame-snap, retime, split, merge, or add gaps. House frame/timing adaptation is a separate validated C4 capability; consume only an already valid profile timing basis.

Use integer/rational time and packet calculations. Quantize only at explicitly selected final boundary by licensed profile rule. Bytes must not vary with locale, wall clock, dictionary order, path, or OS. Empty-document initialization/finalization is a clause-map/defaults decision, not decoder-example behavior.

### Character mapping and unsupported behavior

Map every authored Unicode scalar, newline, and control-sensitive sequence using licensed CTA-708 map version with clause/table references and redistribution decision. Do not reuse 608 data, treat Unicode as mapping proof, normalize combining sequences, or substitute bytes.

For unmappable scalar/combination, unrepresentable layout, unsupported service, or needed undefined window state, preserve the document and report CEA708_UNMAPPABLE_CHARACTER, CEA708_LAYOUT_UNREPRESENTABLE, or CEA708_SERVICE_UNSUPPORTED. Block payload. A manifest may exist only if it says no payload was produced. Never transliterate, drop content, silently move captions between service/window, or emit replacement glyphs.

### Serialization and artifact boundary

Use canonical JSON for profiles/defaults/manifests and a versioned binary serializer for packets. Include encoder/schema, CTA edition/errata, profile/defaults/clause-map/mapping hashes, document/context hashes, service/timing basis, packet/service-block/event ranges, disposition, diagnostics. Exclude operational timestamps, absolute paths, credentials, and machine data from byte/golden hashes.

Do not call output broadcast-ready ATSC, MPEG, transport stream, or container artifact until owner-defined carriage accepts it. Initial development uses clearly internal cea708 schedule JSON plus versioned packet bytes. Transport/mux bridge is separate tested adapter.

## Packets and file ownership

1. 708-N0 evidence: obtain CTA-708 S-2023 and errata; record clause/table matrix, redistribution decision, target chain, support boundary. No code.
2. 708-N1 contracts/defaults: engine/captions/cea708_models.py and cea708_profiles.py, focused tests, strict version/default blocking.
3. 708-N2 mapping/state engine: cea708_mapping.py and cea708_encoder.py, permitted generated data, tests for one service/defaults profile. No writer/UI change.
4. 708-N3 scheduler/serializer: cea708_schedule.py and cea708_serialize.py, packet goldens, independent decoder tests.
5. 708-N4 integration: minimal writer adapter, package/spec inclusion, explicit CLI/UI after owner approval, output-path tests. Coordinate before writer.py edits.
6. 708-N5 acceptance: operator evidence, selected carriage/mux and receiver/broadcast-chain checks, then renewed P13.

## Tests and acceptance

After 708-N0, create goldens for header/packet and service-block boundaries; sequence behavior; selected text-code boundaries; selected control/window/pen transitions; clear/reset/display order; empty document; exact capacity and one unit over; rapid events; multiline events; source-mode unrepresentable timing; invalid context/defaults; unknown service; combining/unmappable characters; corrupt packets; cross-process determinism.

Every fixture asserts:

- Same document/profile/defaults/context produces byte-identical packets and canonical-identical manifests.
- Every byte belongs to a typed clause-mapped operation and emitted text/control links to event/default policy; no unlinked padding or lost text.
- An independent decoder, separately selected and qualified against licensed CTA-708, reconstructs selected service, text, controls, window/state, schedule. Encoder code, shared tables, permissive player behavior, and third-party source are never oracle.
- Altered/malformed bytes fail independent validation.
- Source mode preserves semantic timing/count/order exactly and native attempts leave Manual-Dub CSV byte-identical.

Release acceptance runs samples through owner-selected carriage/mux and representative receiver/decoder chain. Retain captures, chain versions/configuration, service/window/defaults values, decoded text/state, timing observations, and failures in operator-controlled evidence. A conversion, library test, or player screenshot does not prove native-708 delivery support.

## Packaging, support statement, release gate

Package only reviewed modules, deterministic profiles/defaults, redistributable mapping data, fixtures/test tools, and attribution. Register source/wheel/PyInstaller data explicitly; install-test wheel without checkout on PYTHONPATH and smoke-test packaged macOS app. Do not redistribute CTA text, private broadcast captures, or licensed tables without permission.

Until 708-N0 through 708-N5 pass: **The application does not export native CTA-708.** Afterwards state only verified CTA edition/errata, service/defaults profile, character scope, artifact representation, and named accepted carriage/receiver chain. Do not claim CTA-708 compliance, broadcast readiness, all-service support, or positioning/styling support without separate owner-approved conformance evidence.
