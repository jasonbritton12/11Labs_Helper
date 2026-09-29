# P01G glyph-repertoire evidence

`cea608_repertoire_v1.json` is the P01G input for a **mechanical Unicode
repertoire lookup**. It is deliberately not an encoder, a CEA-608 conformance
test, or evidence that a finished SRT/VTT can be delivered as CEA-608.

## Pinned source and redistribution

The data is a source-order transcription of the character-set table published
in [libcaption v0.8 at commit e8b6261090eb3f2012427cc6b151c923f82453db](https://github.com/szatmary/libcaption/blob/e8b6261090eb3f2012427cc6b151c923f82453db/README.md#characters).
The README identifies the Basic North American, Special North American, and
Extended Western European repertoires that libcaption supports for 608. This is
an authoritative statement of that converter's repertoire; it is not a claim
that libcaption is the normative CEA specification.

The source repository's pinned [MIT license](https://github.com/szatmary/libcaption/blob/e8b6261090eb3f2012427cc6b151c923f82453db/LICENSE.txt)
permits copying and redistribution with the copyright and permission notice.
The JSON records that notice and says that it reformats the published
repertoire only. No converter source code is included.

The normative reference is [ANSI/CEA-608-E-2008 (R2014)](https://webstore.ansi.org/preview-pages/CEA/preview_ANSI%2BCEA%2B608-E-2008%2BR2014.pdf).
Its preview identifies CEA as the publisher, says the document is all rights
reserved, and lists the character tables in its contents. Its tables are not
copied into this repository; the pinned MIT-licensed converter repertoire is
the redistributable data source.

## Data contract

The JSON is versioned and deterministic. `character_sets` and each `glyphs`
array preserve the published table order. A glyph is mechanically supported
only if its exact Unicode scalar occurs in one of those arrays. This avoids
the false shortcuts of ASCII-only, Latin-1, Unicode normalization, or silent
replacement.

For example, the data records accented letters (`é`), punctuation (`—`, `’`),
and the music symbol (`♪`). A glyph such as `€` or `😀` is **not listed by the
pinned repertoire**. That status is intentionally
`unverified_not_supported_by_pinned_repertoire`, rather than a claim about
every normative CEA-608 implementation. Future QC must retain such a glyph in
the draft and report its code point and source position.

## Boundary for P05 and later work

P05 may consume this file only for exact repertoire membership and glyph
findings. The data explicitly leaves all of the following unverified:

- Unicode-to-byte selection and actual CEA-608 byte generation.
- Control-code overhead, parity, channel/field behavior, and transmission.
- Downstream conversion, decoder behavior, and player acceptance.

Those are C4 delivery checks. Passing this lookup does not permit a
"608-compatible authoring" or certification claim. A later native-608
implementation needs a named encoder, transport profile, golden byte fixtures,
and destination acceptance evidence.
