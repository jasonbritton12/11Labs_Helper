# C4 implementation plan index

Prepared 2026-09-28. These are implementation packets, not delivered C4
features. The current branch exports rulebook-authored SRT/WebVTT only. It does
not yet perform exact frame conversion, shot-aware timing, named destination
validation, TTML/IMSC serialization, or native CTA-608/CTA-708 encoding.

## Governing boundaries

- The [608/708/Web house rulebook](../universal-caption-authoring-rule_608-708-web.md)
  remains the authoring policy. Destination rules may tighten a named export,
  but may not weaken content preservation or source integrity.
- `source` mode keeps source cue count, order, starts, and ends. A destination
  conflict is reported and blocks strict delivery; the exporter does not snap,
  split, merge, round, or retime it.
- Caption authoring remains text and timing only. Any format-required service,
  window, region, row, or mode value must be a transparent, versioned delivery
  default approved for a named destination. It is never inferred positioning
  or styling intent.
- Manual-Dub CSV, canonical history, speaker edits, caption overlays, and
  approvals remain outside destination encoding and retain their existing
  invariants.
- A schema parse or one downstream conversion is not a support claim. Each
  format needs its own primary-spec map, independent round trip, package proof,
  named converter/player or carriage acceptance, and narrow support statement.

## Packet order

| Order | Packet | Purpose | Entry gate | Current state |
|---:|---|---|---|---|
| 1 | [Exact frame alignment and conversion](C4_FRAME_ALIGNMENT_PLAN.md) | Introduce rational grids, boundary policies, conversion evidence, and source incompatibility reporting. | Owner-selected grids and endpoint policy; licensed SMPTE text before drop-frame labels. | Plan ready; no implementation. |
| 2 | [Shot context and hang checks](C4_SHOT_CONTEXT_PLAN.md) | Accept provenance-bearing shot observations and evaluate hangs without inventing cuts. | Approved observation sources, tolerances, coverage, and policy thresholds. | Plan ready; no implementation. |
| 3 | [Named destination overrides](C4_DESTINATION_OVERRIDES_PLAN.md) | Resolve immutable, evidence-backed destination contracts and artifact manifests. | First destination/receiver and evidence-retention owner decisions. | Plan ready; no implementation. |
| 4 | [Generic TTML2 exporter](C4_TTML2_EXPORTER_PLAN.md) | Serialize a minimal generic TTML2 sidecar and prove semantic/XML interoperability. | C1-C3/P13, time-precision decision, independent validator, named converter/player. | Plan ready; no implementation. |
| 5 | [IMSC 1.3 Text exporter](C4_IMSC1_EXPORTER_PLAN.md) | Add a separately signaled IMSC 1.3 Text Profile deliverable for an accepted receiver. | Accepted TTML2 primitives plus IMSC validator/HRM and named receiver acceptance. | Plan ready; no implementation. |
| 6 | [Native CTA-608 exporter](C4_CEA608_EXPORTER_PLAN.md) | Build one clause-mapped native-608 profile, scheduler, serializer, and delivery-chain proof. | Licensed ANSI/CTA-608-E S-2019 access, reviewed clause/table map, approved defaults, independent decoder. | Plan ready; normative implementation blocked. |
| 7 | [Native CTA-708 exporter](C4_CEA708_EXPORTER_PLAN.md) | Build one independent clause-mapped DTVCC profile, scheduler, serializer, and carriage proof. | Licensed ANSI/CTA-708-E S-2023 plus errata, reviewed clause/table map, approved defaults, independent decoder. | Plan ready; normative implementation blocked. |

The order freezes shared rational/context/destination contracts before exporter
integration and keeps each support claim independently reviewable. TTML2 precedes
IMSC. Native 608 and 708 are separate encoders; neither is evidence for the
other. Only one exporter packet should own shared writer/config/CLI files at a
time.

## Required release evidence per delivered packet

Each implementation packet must add deterministic goldens, negative fixtures,
source-mode incompatibility tests, Manual-Dub byte-invariance checks, and package
asset checks. It must record the exact primary specification edition/errata,
clause or section map, tool names/versions, independent semantic round trip,
and the named player, receiver, decoder, converter, mux, or carriage boundary
used for acceptance. Renew P13 after every exporter or context capability before
changing its status from planned to supported.

CTA catalog pages establish current document identity and scope only. Native
608/708 coding work and claims remain blocked until the permitted normative text
has been obtained and reviewed; third-party libraries and existing glyph data
are not substitutes.
