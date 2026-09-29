# C4 IMSC 1 Text exporter packet

**Status:** planning only. Execute this packet only after the TTML2 packet has
passed its independent gate. It is a separate IMSC 1.3 Text Profile exporter,
not a switch on the generic TTML2 renderer and not a claim of IMSC 1.2 or Image
Profile support.

**Authority and retrieval.** Sources below were retrieved **2026-09-28**. IMSC
1.3 is the current applicable W3C Recommendation; IMSC 1.2 remains a compatibility
input only when a named receiver contract explicitly requires it.

- [IMSC Text Profile 1.3](https://www.w3.org/TR/ttml-imsc1.3/) — **normative**
  W3C Recommendation (21 May 2026): Text Profile scope, designator, feature
  constraints, UTF-8 encoding, namespaces, profile signaling, character guidance,
  and IMSC-specific requirements.
- [IMSC 1.2](https://www.w3.org/TR/ttml-imsc1.2/) — **normative only for an
  explicitly selected 1.2 compatibility mode**. Do not silently target it from a
  1.3 export.
- [TTML2](https://www.w3.org/TR/ttml2/) — **normative** base specification for
  XML structure, timing and profile semantics; IMSC 1.3 is a text profile of it.
- [IMSC 1.3 Recommendation status and implementation report](https://www.w3.org/TR/2026/REC-ttml-imsc1.3-20260521/)
  — **informative W3C release/implementation evidence**; use it to select test
  inputs and independent acceptance, not as a content validator.
- [TTML media type and profile registry](https://www.w3.org/TR/ttml-profile-registry/)
  — **informative W3C Group Note**. It registers IMSC 1.3 Text as `im4t` and
  `.ttml`/`application/ttml+xml`; it does not replace the IMSC Recommendation.
- [BCP 47 / RFC 5646](https://www.rfc-editor.org/rfc/rfc5646) — **normative
  IETF language-tag syntax and processing reference** for `xml:lang` validation.

## 1. Problem, scope, and execution order

An IMSC consumer needs an explicitly signaled, text-only TTML2 profile rather
than generic TTML. This packet serializes an accepted `CaptionDocument` as an
**IMSC 1.3 Text Profile** document with designator
`http://www.w3.org/ns/ttml/profile/imsc1.3/text`. It preserves the product’s
authoring boundary: captions carry already-authored text, line breaks, and event
times only. Required structural/profile boilerplate is allowed; authored
presentation is not.

Execution order is fixed:

1. accept the generic TTML2 serializer and its XML/schema/semantic round-trip
   gates; then
2. implement this IMSC serializer as a distinct deliverable, fixtures, profile
   validator configuration, converter, and player acceptance set.

The IMSC serializer may reuse only the accepted generic XML escaping, canonical
decimal time, deterministic ID, staging, and parse-projection primitives. It must
not inherit generic TTML output unchanged, assume its profile compatibility, or
make IMSC feature choices in a shared serializer without IMSC tests.

This packet excludes IMSC Image Profile, images, bitmap captions, external or
embedded font resources, styles, regions, layout, colors, font selection/size,
padding, alignment, active area, aspect-ratio mapping, forced display, visibility,
animation, ruby, text emphasis, karaoke, captions placed around picture content,
MPEG-DASH/HLS/MP4 packaging, codec signaling, and all 608/708 conversion. It also
does not make an IMSC 1.2 deliverable. A receiver that demands any excluded
feature requires a separately named destination profile and owner approval.

## 2. Dependencies and frozen interfaces

C1--C3/P11 gates, the accepted TTML2 packet, and a named IMSC receiver/player
are prerequisites. The generic serializer’s source timing and XML security
checks are inherited but must be rerun through the IMSC suite. IMSC feature and
profile findings join the current `CaptionQCReport`; strict/draft disposition
continues to flow through `ExportResult`.

| Frozen input | IMSC 1.3 responsibility |
|---|---|
| `CaptionDocument` and its profile/options | Read-only input. The IMSC destination selection is a new explicit destination profile, versioned independently of the house profile; it must not mutate the document hash. |
| `CaptionEvent` | One ordered `p` per event, exact text/line breaks, deterministic `xml:id`, and exact canonical-decimal `begin`/`end`. |
| source-mode ledger | Preserve count, order, starts, ends, source linkage, and text exactly. If required IMSC representation/validation would demand a change, block with an incompatibility finding. Never frame-snap or retime. |
| `CaptionSource.language_code` | Consume the accepted, versioned BCP 47 validation result from the TTML2 foundation. Emit canonical valid `xml:lang` only; do not infer a language. Invalid, missing, private-use-only, and unsupported-for-analysis states remain distinct and visible. |
| QC, overlay, approval, history, Manual-Dub | Preserve their existing roles and hashes. IMSC output neither creates approvals nor changes overlay/canonical/CSV data. |
| `CaptionContext` | Do not consume frame rate, duration, shots, active-area, or video geometry in this first IMSC packet. Those are separate C4 context/destination decisions. |

Proposed API, separate from generic TTML2:

```python
render_imsc1_text_document(document: CaptionDocument, *, language_code: str | None,
                           profile: IMSCTextDestinationProfile) -> str
parse_imsc1_text_export(xml: str) -> ParsedIMSCTextDocument
validate_imsc1_text_export(xml: str, document: CaptionDocument,
                           profile: IMSCTextDestinationProfile) -> FormatValidationReport
```

Define a `Deliverable.IMSC1_TEXT` (final public spelling is an owner decision)
with its own collision-free `<stem>.imsc1.3.ttml` planned path and sidecar/writer
behavior. Before staging, assert that every requested deliverable has a globally
unique artifact path. Explicitly reject a
batch requesting both generic TTML2 and IMSC from one undifferentiated profile;
they may share a `CaptionDocument` only when each destination profile is resolved,
recorded, and independently validated. No legacy wrapper may silently add IMSC.

## 3. IMSC 1.3 data model and serialization

The minimal profile-safe form is:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<tt xmlns="http://www.w3.org/ns/ttml"
    xmlns:ttp="http://www.w3.org/ns/ttml#parameter"
    xml:lang="en"
    xml:space="default"
    ttp:timeBase="media"
    ttp:contentProfiles="http://www.w3.org/ns/ttml/profile/imsc1.3/text">
  <body><div>
    <p xml:id="caption_event_..." begin="12.345s" end="14.678s">First line<br/>Second line</p>
  </div></body>
</tt>
```

The IMSC Recommendation says `ttp:contentProfiles` **SHOULD** be present with
exactly one value equal to the Text Profile designator. This exporter therefore
emits that single exact value, a deterministic interoperability choice, not a
claim about an additional profile. It emits `ttp:timeBase="media"` explicitly
and all times as decimal `s` offset-time expressions. No frame/tick/clock/SMPTE
syntax, `dur`, inherited timing, `ttp:frameRate`, `ttp:tickRate`,
`ttp:displayAspectRatio`, root extent, or profile-combination attributes are
emitted.

`head` is omitted. In particular, do not create `styling`, `layout`, `region`,
`metadata`, EBU-TT metadata, `ebuttm:conformsToStandard`, or IMSC extension
elements. `br` is the only text-structure element below `p`. A `p` without a
region intentionally uses the default region, so the exporter does not author a
location. The renderer must not infer defaults as product-chosen style or
positioning. It must emit neither `tts:*` nor `itts:*` attributes.

The event-to-XML mapping, canonical decimal formatter, XML 1.0 escaping,
forbidden-character behavior, XML-ID encoding/collision check, LF formatting,
and parse-back semantic projection are identical to the accepted TTML2 packet.
IMSC adds these format checks:

| IMSC rule | Required action |
|---|---|
| UTF-8 well-formed XML 1.0 | Write UTF-8, retain and verify the XML declaration/bytes, and parse independently with external entity/network resolution disabled. Emit no DOCTYPE or entity declaration and no non-predefined entity reference. |
| IMSC 1.3 Text designator | Require the single exact `ttp:contentProfiles` value on root and reject a different/multiple/missing value. |
| text-only scope | Reject images/resources/font references and every style/layout/presentation directive; do not remove or transform them because this serializer never accepts them as input. |
| language/characters | Preserve all valid Unicode. Run the IMSC common-character-set analysis only when `xml:lang` is known; present an advisory `IMSC1_CHARACTER_SET_UNVERIFIED` when it is unknown or the language is unsupported. Never replace a character. |
| complexity | Run an IMSC Hypothetical Render Model check with the selected profile tool/configuration. A failure or unavailable checker is a blocking delivery validation gap, never a content rewrite. |

IMSC 1.3 includes new language/typographic capabilities and supersedes IMSC 1.2
for this profile; this application does not emit those presentational features.
The owner may later add a **separate** explicit `imsc1.2-text` destination profile
with the 1.2 designator `http://www.w3.org/ns/ttml/profile/imsc1.2/text`, a
separate golden corpus, and a legacy receiver acceptance matrix. It must not be
an automatic fallback after a 1.3 rejection.

## 4. Unsupported behavior, deterministic output, and failures

| Input or request | Required disposition |
|---|---|
| invalid/unrenderable event, unknown schema, unsafe/duplicate XML ID, invalid XML character, parser/schema/profile/HRM failure | block IMSC output and add stable `IMSC1_*` finding; never write a file marked conformant |
| source timing not representable under frozen decimal semantics, or a requested frame alignment | `IMSC1_SOURCE_TIMING_INCOMPATIBLE`; no rounding, snap, split, merge, or retime |
| unknown/unvalidated language | omit `xml:lang`, report it; draft policy may be considered only if the IMSC owner accepts character-set validation as unavailable, but no IMSC support claim until resolved |
| style, region, forced/display metadata, font, image, packaging, receiver-specific requirement | `IMSC1_DESTINATION_PROFILE_REQUIRED`; do not invent boilerplate or presentation |
| existing house/glyph/readability QC failure | retain current draft/strict disposition and faithful text/timing; do not hide it through IMSC markup |
| empty document | block until the IMSC receiver owner accepts a test file and playback semantics; do not assume empty default-region behavior is useful |

Byte determinism is mandatory: fixed XML declaration/namespace prefixes and
order, root-attribute order, exact designator, body/div/p ordering, `br` output,
XML escaping, decimal formatting, IDs, UTF-8 bytes, LF/newline policy, and final
LF. The output contains no generated date, host/path, random value, comment, or
provenance metadata. IMSC format fields and validation tool identity belong in
the format report/sidecar, excluded from existing document/report identity unless
the core contract is formally versioned.

## 5. Packaging, golden corpus, and round trips

Own `engine/exporters/imsc1.py`, an isolated IMSC validation adapter, profile
configuration, fixtures, targeted writer/config/CLI/packaging registration, and
tests. Do not modify the generic TTML2 tests to mask IMSC requirements. Register
the module/fixture/profile data in the wheel and PyInstaller build. Pin and record
the exact W3C IMSC/TTML schema snapshot, HRM checker/tool configuration, hashes,
licenses, URLs, and retrieval date. No export may retrieve schemas/tools over the
network.

Create `tests/fixtures/captions/imsc1.3-text/` with an input document, expected
TTML, parsed semantic projection, expected profile/HRM outcome, and destination
acceptance record for every case:

1. valid single-line and `br` two-line text, XML escaping, non-BMP/combining
   Unicode, supported language tags, unknown language, and required root profile
   signaling;
2. source-mode sub-millisecond decimals, overlaps/equal starts/zero gaps, long
   times, and a failing no-frame-snap proof; house-mode counterparts without
   changing authored text;
3. invalid profile designator/multiple profiles, wrong namespace, absent/invalid
   media timebase, unsupported `tts`/`itts`/region/layout/style/metadata/resource
   constructs, XML injection/DOCTYPE/entity attempts, XML-ID collision, and
   forbidden code point;
4. IMSC complexity/HRM boundary cases selected from the official W3C test corpus
   and a corpus version/commit pinned in evidence; and
5. current content ledger, caption document/QC sidecar hashes, strict/draft
   behavior, atomic write failure, and Manual-Dub byte invariance.

Round-trip comparison parses generated XML through a hardened independent parser
and compares root namespace/designator/timebase, `p` count/order/IDs, decimal
times, line break sequence, and decoded Unicode text with the original document.
It must separately verify forbidden vocabulary is absent. It may not reconstruct
the document by reading generated output with the production serializer.

## 6. Exact independent acceptance checks

Add targeted tests and run these required checks before the support statement is
enabled:

```text
.venv/bin/python -m pytest \
  tests/test_imsc1_renderer.py tests/test_imsc1_validation.py \
  tests/test_imsc1_writer.py tests/test_ttml2_renderer.py \
  tests/test_caption_renderers.py tests/test_caption_writer.py \
  tests/test_caption_source.py tests/test_caption_qc.py tests/test_dub_csv.py
.venv/bin/python -m compileall -q elevenlabs_helper
git diff --check
```

The release evidence must show, with exact versioned commands and artifacts:

1. independent XML well-formedness/security parse and a W3C TTML schema check
   (useful but not a substitute for profile conformance);
2. a separately implemented IMSC 1.3 Text validator/verifier that accepts the
   valid corpus, rejects invalid profile cases, and reports the configured HRM
   result; if no suitable independently implemented verifier is reproducible,
   IMSC support remains unclaimed;
3. selected positive/negative tests from the official W3C IMSC test corpus and
   Recommendation-linked implementation evidence, pinned by source revision;
4. a named, versioned target IMSC converter/packager and at least one named,
   versioned IMSC presentation player/device, with capture/log evidence that
   every supported fixture loads, has expected text/order/timing, and does not
   require un-authored placement/style; and
5. wheel install/import and PyInstaller smoke checks proving serializer, profile
   data, schema assets, and validation adapter are included offline.

The W3C Recommendation distinguishes transformation and presentation processors;
schema parsing, a validator, a converter, and a player therefore cover different
acceptance boundaries. One successful downstream conversion alone does not close
this packet.

## 7. Support statement and owner decisions

After all gates pass, the only permitted statement is: “Exports deterministic,
text-and-timing-only IMSC 1.3 Text Profile `.ttml` sidecars for the accepted
receiver/version and golden corpus, with no authored styling or positioning.”
Do not promise IMSC Image, IMSC 1.2, Dash/HLS/MP4 packaging, broadcast caption
conversion, universal device rendering, or safe-area placement.

Before implementation, record these owners and decisions:

1. **Caption policy owner:** exact decimal/source-timing precision rule, unknown-
   language disposition, empty-document policy, and whether an HRM failure blocks
   draft as well as strict output.
2. **Destination owner:** first receiver, its IMSC 1.3 requirement, packaging
   handoff, target converter/player/device versions, and acceptance sample.
3. **Implementation owner:** final public deliverable name, isolated IMSC profile
   configuration, serializer/validator interfaces, asset pinning, and deterministic
   output.
4. **QA owner:** independent validator and HRM evidence, W3C corpus revision,
   converter/player captures, and packaged offline verification.

Any unresolved decision blocks a corresponding IMSC support assertion. It never
permits a silent fallback to generic TTML2/IMSC 1.2, inferred style/positioning,
or source timing change.
