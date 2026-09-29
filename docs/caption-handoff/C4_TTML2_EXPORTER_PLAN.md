# C4 TTML2 exporter packet

**Status:** planning only. Implement this packet before the IMSC packet. It does
not authorize a TTML/IMSC support claim, a code change, or a destination-specific
delivery promise.

**Authority and retrieval.** The implementation owner must pin the sources below
in the implementation record and re-check their publication/errata state before
release. All were retrieved **2026-09-28**.

- [TTML2](https://www.w3.org/TR/ttml2/) — **normative** W3C TTML2
  specification: document structure, timing, profiles, namespaces, validation,
  and content conformance.
- [TTML2 schemas appendix](https://www.w3.org/TR/ttml2/#schemas) —
  **normative appendix**. Its supplied XSD/RNC schemas are useful checks, but
  the specification says the body defines formal validity when the schema differs.
- [TTML media type and profile registry](https://www.w3.org/TR/ttml-profile-registry/)
  — **informative W3C Group Note** for this exporter: `.ttml`,
  `application/ttml+xml`, and registered profile identifiers. It must not be
  treated as a content-profile definition.
- [TTML2 implementation report](https://www.w3.org/wiki/TTML/TTML2ImplementationReport)
  — **informative W3C implementation evidence**. Use it to select independent
  validator acceptance, not as a replacement for document conformance.
- [BCP 47 / RFC 5646](https://www.rfc-editor.org/rfc/rfc5646) — **normative
  IETF language-tag syntax and processing reference** for `xml:lang` validation.

## 1. Problem, scope, and non-goals

The current caption pipeline produces a deterministic `CaptionDocument` and
`CaptionQCReport`, then SRT/VTT. This packet adds a **generic TTML2 document
serializer** that maps one already-interpreted document to well-formed TTML2
without changing its wording, event order, line breaks, or timing.

The output is a UTF-8 `.ttml` text sidecar, suitable for interchange as
`application/ttml+xml` when a consuming delivery protocol chooses that media
type. It is deliberately **not** an IMSC, EBU-TT-D, SMPTE, DASH, HLS, 608, or
708 exporter. A named destination profile may be added only by its own accepted
packet. This packet may not advertise generic TTML2 output as conforming to one
of those profiles merely because the XML also parses there.

Non-goals are presentation authoring and conversion: no regions, layout,
styling, font, color, alignment, placement, root extent, display aspect ratio,
animation, resources, images, audio, metadata inferred from the program, active
area, forced-display behavior, or frame snapping. No cue may be split, merged,
retimed, normalized, transliterated, or rewritten for XML. This packet neither
changes source/house interpretation nor creates a player renderer.

## 2. Entry gate, dependencies, and frozen interfaces

Do not start code until C1--C3 and P11 have passed their independent release
gate. The exporter consumes a complete, non-blocked interpretation. Draft policy
may write a clearly reported draft only through the existing `ExportResult`
rules; strict policy blocks on the existing QC/approval state. Technical XML or
TTML failure always blocks the TTML file, even in draft mode.

The implementation must use these frozen inputs without changing their meanings:

| Frozen boundary | TTML2 obligation |
|---|---|
| `CaptionDocument` | Use its ordered `events`, `profile`, resolved `options`, hashes, and provenance as read-only input. Do not add format facts to `document_hash`. |
| `CaptionEvent` | One `p` per event, in event order; map `start`, `end`, `authored_lines`, `event_id`, `source_token_indices`, `content_kind`, and `timing_mode` without a timing/content mutation. |
| `CaptionSource` / source-mode ledger | In `source` mode, cue count/order/start/end and source linkage must survive both TTML serialization and parse-back validation. A destination incompatibility is a reported `TTML2_*` finding, never an auto-retime. |
| `CaptionQCReport` / `ExportResult` | Add format findings and written path through a format-specific result; retain existing draft/strict, approval, sidecar, atomic-stage, and partial-replace semantics. |
| `CaptionContext` | Ignore frame rate, shots, duration, and presentation facts in this generic packet. A separate C4 packet owns exact rational frame conversion/alignment. |
| canonical/speaker/Manual-Dub paths | Do not edit canonical cues, overlays, speaker mapping, history, or Manual-Dub CSV. The byte-for-byte Manual-Dub invariant remains a release check. |

Proposed narrow API, owned by `engine/exporters/ttml2.py`:

```python
render_ttml2_document(document: CaptionDocument, *, language_code: str | None) -> str
parse_ttml2_export(xml: str) -> ParsedTTML2Document  # test/verification boundary
validate_ttml2_export(xml: str, document: CaptionDocument) -> CaptionQCReport | FormatValidationReport
```

Before exporter work, add a versioned `engine/captions/language_tags.py`
validator shared by TTML2 and IMSC. `CaptionSource.language_code` is currently
an unrestricted string; no existing validator may be assumed. The validator
returns raw input, canonical BCP 47 form, primary language, validation status,
and validator version. It accepts syntactically valid two- or three-letter
primary tags such as `en` and `eng`, canonicalizes case for `en-US`, rejects
underscores and malformed tags, preserves valid private-use tags while marking
their language-specific analysis unavailable, and distinguishes missing from
invalid. Bind the result/version into format evidence and cover grandfathered,
extension, private-use, and unknown values. Invalid tags never reach `xml:lang`.

`render_ttml2_document` is pure and has no timestamps, filesystem access, or
network access. `writer.py` owns staging and replacement. Add a distinct
`Deliverable.TTML2` (wire/CLI value `ttml2` only if backward compatibility allows;
otherwise owner chooses the final public value before implementation),
collision-free `<stem>.ttml2.ttml` path planning, and no implicit conversion of
SRT/VTT requests. Keep the legacy
`write_deliverables()` path contract: it returns only actual paths.

## 3. Normative serialization contract

Serialize a minimal TTML2 document in a fixed element/attribute order:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<tt xmlns="http://www.w3.org/ns/ttml"
    xmlns:ttp="http://www.w3.org/ns/ttml#parameter"
    xml:lang="en"
    xml:space="default"
    ttp:timeBase="media">
  <body><div>
    <p xml:id="caption_event_..." begin="12.345s" end="14.678s">First line<br/>Second line</p>
  </div></body>
</tt>
```

This is a shape specification, not an exact pretty-print requirement. The XML
declaration, UTF-8 encoding, TTML namespace, `ttp:timeBase="media"`, `body`,
one `div`, one `p` per event, `begin`, `end`, `xml:id`, and `br` line boundaries
are the only emitted boilerplate. Do not emit `head`, `metadata`, `styling`,
`layout`, `region`, `style`, `tts:*`, `ttm:*`, `ttp:contentProfiles`, feature
declarations, profile declarations, or `xml:space="preserve"`. `xml:lang` is
emitted only when `CaptionSource.language_code` has passed the new versioned
BCP 47 validation contract; otherwise omit it and issue
`TTML2_LANGUAGE_UNKNOWN` or `TTML2_LANGUAGE_INVALID`.
Never guess `en` or a region tag.

### Event and text mapping

| Caption input | TTML2 representation | Required check |
|---|---|---|
| `event_id` | Unique valid XML `xml:id` on the event `p`; use a deterministic XML-name-safe encoding of the event ID, with a collision check. | Parse-back maps each `p` to exactly one original event. |
| `start`, `end` | `begin` and `end` on the same `p`; no `dur`, inherited timing, frame, tick, or clock expression. | Parsed values equal the canonical decimal form of each input value. |
| `authored_lines` | XML text nodes separated only by TTML `<br/>` elements. | Line count and every Unicode scalar sequence match after XML entity decoding. |
| event order | `p` sibling order in one `div`. | Parsed order equals `CaptionDocument.events` order, including equal starts. |
| speaker/content/source/provenance/QC hashes | Remain in JSON sidecars and internal report, not unstandardized TTML attributes or inferred `ttm:*` metadata. | Sidecars retain their current hash contract. |

Use decimal **offset-time** seconds (`<canonical-decimal>s`) for every `begin`
and `end`, with the same syntax throughout the document. Convert the finite
in-memory numeric value once through the project canonical decimal rule (initial
implementation: `Decimal(str(value))`, fixed-point, no exponent, no forced
millisecond rounding, no trailing fractional zero unless needed). Reject negative,
non-finite, reversed, or zero-duration events before serialization. Do not use
frames, ticks, SMPTE timecode, or subtraction to derive `dur`; source mode has no
permission to snap to a frame. If an exact source value cannot be represented by
the frozen numeric contract, issue `TTML2_SOURCE_PRECISION_UNREPRESENTABLE` and
block instead of choosing a nearby value.

Escape XML characters through the XML serializer, never by string interpolation.
Reject XML 1.0-forbidden code points before writing. Preserve valid Unicode text
as code points; do not replace unsupported glyphs. Existing glyph/profile QC
findings remain visible, and a delivery profile may later add its own repertoire
test. The document contains no DOCTYPE, entity declaration, processing
instruction beyond the XML declaration, or entity references except XML predefined
entities created by serialization.

## 4. Unsupported feature behavior and deterministic output

The serializer must fail closed with structured, stable finding codes. Examples:

| Condition | Result |
|---|---|
| event invalid, document blocked, unknown schema, duplicate/unsafe XML ID, non-XML character, failed serializer/parser/TTML validation | no `.ttml`; `BLOCKED`; preserve diagnostic sidecars where current writer policy permits |
| source-mode cue cannot be represented without rounding or frame alignment | no `.ttml`; `TTML2_SOURCE_TIMING_INCOMPATIBLE`; no retime |
| destination asks for styling, placement, `head` metadata, a TTML profile, media packaging, or a feature outside this packet | do not approximate; report `TTML2_DESTINATION_PROFILE_REQUIRED` and route to a named destination packet |
| style/glyph/reading-speed QC failure | preserve current draft/strict policy; never alter text/timing to hide it |
| no events | emit valid, deterministic empty `body/div` only after owner accepts the empty-document interoperability fixture; otherwise report an explicit decision-required failure |

Repeated calls with byte-identical document/options/language input must produce
byte-identical UTF-8 output. Fix namespace prefixes (`ttp`), namespace declaration
order, XML declaration, indentation/newline policy (LF, final LF), `p` order,
attribute order, decimal formatting, and ID encoding. Do not include wall-clock
time, host paths, generator version text, random IDs, or an XML comment. Canonical
caption JSON remains the source of identity; formatting cannot change its hashes.

## 5. Packaging and integration work

Own only the TTML2 renderer, a narrow validation adapter, fixture data, tests,
and targeted writer/config/CLI/packaging registration. Register the module and
fixtures in `pyproject.toml` and the PyInstaller spec so installed wheels and the
desktop build contain them. Pin any local XML/schema/verifier dependency and its
license/version in the implementation record; no network fetch occurs at export.

The package must include the exact W3C schema snapshot used for an *additional*
schema check, its SHA-256 and retrieval URL/date, or run it only as an external CI
artifact. The plan must not describe XSD/RNC success as TTML2 conformance: the
TTML2 normative text controls. Avoid bundling a third-party converter as proof of
support. The write path stages `.ttml` beside the requested target, fsyncs it,
then uses the current atomic replacement/error reporting pattern with caption
document and QC sidecars.

## 6. Golden corpus, round trips, and acceptance gates

Create a versioned `tests/fixtures/captions/ttml2/` corpus with source document,
expected `.ttml`, parsed semantic projection, and expected findings. Include:

1. one and two authored lines (`br`), XML escaping, Unicode combining characters,
   emoji/non-BMP valid XML characters, and punctuation;
2. source-mode events at sub-millisecond decimal boundaries, zero gap, overlaps,
   equal starts, long hour values, and a source-mode failure that proves no snap;
3. house-mode equivalent output, speaker/audio-event text already authored by the
   interpretation layer, empty document decision, and invalid source events;
4. every XML edge: unsafe ID, duplicate encoded ID, control character, `&`, `<`,
   quotes, forbidden entity/DOCTYPE injection attempt, unknown language, and
   blocked strict/draft states;
5. fixtures proving absence of every style/layout/profile/metadata/presentation
   directive and unchanged Manual-Dub CSV bytes.

Exact checks, all required before support is claimed:

```text
.venv/bin/python -m pytest \
  tests/test_ttml2_renderer.py tests/test_ttml2_writer.py \
  tests/test_caption_renderers.py tests/test_caption_writer.py \
  tests/test_caption_source.py tests/test_caption_qc.py tests/test_dub_csv.py
.venv/bin/python -m compileall -q elevenlabs_helper
git diff --check
```

Add and execute checks that (a) parse output with an independent XML parser with
external entity/network resolution disabled, (b) validate against the pinned W3C
XSD or RNC snapshot, (c) compare the parsed semantic projection with every event
and source-mode ledger, and (d) run a selected set of official TTML2 positive and
negative tests from the cited W3C test evidence where their licenses/fixtures are
recorded. A separate, independently implemented TTML validator/verifier must
accept the golden valid corpus and reject the invalid corpus. Record its exact
name, version, invocation, input/output, and exit code; schema-only validation is
insufficient. Finally, an owner-selected TTML2-capable destination converter and
player must load every supported golden file and demonstrate event text/order and
start/end behavior. Their product/version/platform/logs belong in release
evidence; no player is assumed by this generic packet.

## 7. Support statement and owner decisions

Support can be stated only as: “Exports deterministic, minimal, text-and-timing-
only TTML2 sidecars for the accepted generic TTML2 corpus; no destination profile
or presentation fidelity is claimed.” Do not call it “broadcast TTML,” “IMSC,” or
“player-certified.”

Before coding, the caption owner must decide and record:

1. the public deliverable token/name and whether an empty timed-text document is
   supported;
2. the exact finite-time precision policy required by the frozen float contract,
   including whether `Decimal(str(value))` is acceptable for source guarantees;
3. the independent validator/verifier and the destination converter/player with
   reproducible access; and
4. the first real delivery profile/customer and its separately versioned packet.

The implementation owner owns renderer, validation, fixtures, and package
registration. The caption policy owner approves precision and empty-output policy.
The destination owner supplies profile rules and player acceptance. QA owns the
independent validator/converter/player evidence. A missing decision blocks only
the affected support claim; it never authorizes inferred positioning or retiming.
