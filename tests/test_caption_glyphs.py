"""P01G data-only verification; the caption package is not yet integrated."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from elevenlabs_helper.engine.captions import (
    UnsupportedGlyph,
    is_supported_glyph,
    repertoire_metadata,
    unsupported_glyphs,
)

DATA_PATH = (
    Path(__file__).resolve().parents[1]
    / "elevenlabs_helper"
    / "engine"
    / "captions"
    / "data"
    / "cea608_repertoire_v1.json"
)


def _load_repertoire() -> dict[str, object]:
    with DATA_PATH.open(encoding="utf-8") as source:
        return json.load(source)


def _glyphs_by_set(data: dict[str, object]) -> dict[str, set[str]]:
    return {
        character_set["id"]: set(character_set["glyphs"])
        for character_set in data["character_sets"]
    }


def _all_glyphs(data: dict[str, object]) -> set[str]:
    return set().union(*_glyphs_by_set(data).values())


def test_cea608_repertoire_data_has_versioned_schema_and_pinned_provenance() -> None:
    data = _load_repertoire()

    assert data["schema_id"] == "elevenlabs-helper.caption.cea608-repertoire"
    assert data["schema_version"] == "1.0.0"
    assert data["data_version"] == "1.0.0"
    assert data["status"] == "verified_repertoire_lookup_only"

    converter_source, normative_source = data["sources"]
    assert converter_source["version"] == "v0.8"
    assert converter_source["commit"] == "e8b6261090eb3f2012427cc6b151c923f82453db"
    assert converter_source["license_spdx"] == "MIT"
    assert converter_source["redistribution_status"] == "redistributable_with_MIT_notice"
    assert normative_source["redistribution_status"] == "not_copied_into_this_dataset"
    assert data["redistribution"]["derived_data_license"] == "MIT"


def test_cea608_repertoire_has_representative_accent_punctuation_and_music_glyphs() -> None:
    data = _load_repertoire()
    glyphs_by_set = _glyphs_by_set(data)
    glyphs = _all_glyphs(data)

    assert "é" in glyphs_by_set["BNA"]
    assert "—" in glyphs_by_set["WES"]
    assert "’" in glyphs_by_set["BNA"]
    assert "♪" in glyphs_by_set["SNA"]
    assert {"é", "—", "’", "♪"} <= glyphs


def test_not_listed_glyphs_are_unverified_not_silently_replaced() -> None:
    data = _load_repertoire()
    glyphs = _all_glyphs(data)

    assert "€" not in glyphs
    assert "😀" not in glyphs
    assert data["not_listed_glyph_disposition"]["status"] == (
        "unverified_not_supported_by_pinned_repertoire"
    )
    assert "Do not replace" in data["not_listed_glyph_disposition"]["required_behavior"]


def test_repertoire_lookup_is_not_an_actual_cea608_encoding_claim() -> None:
    data = _load_repertoire()
    boundaries = data["verification_boundaries"]

    assert boundaries["mechanical_unicode_repertoire_lookup"] == (
        "verified_for_pinned_libcaption_v0_8"
    )
    assert boundaries["actual_cea608_byte_generation"] == "unverified"
    assert boundaries["downstream_transcoding_and_player_acceptance"] == "unverified"
    assert "Do not claim" in boundaries["claim_gate"]


def test_runtime_lookup_exposes_pinned_metadata_and_exact_membership_only() -> None:
    metadata = repertoire_metadata()

    assert metadata["schema_id"] == "elevenlabs-helper.caption.cea608-repertoire"
    assert metadata["status"] == "verified_repertoire_lookup_only"
    assert metadata["repertoire_id"] == (
        "cea608-libcaption-v0.8-e8b6261090eb3f2012427cc6b151c923f82453db"
    )
    assert metadata["character_set_ids"] == ("BNA", "SNA", "WES", "WEF", "WEP", "WEG")
    assert is_supported_glyph("é") is True
    assert is_supported_glyph("—") is True
    assert is_supported_glyph("♪") is True
    assert is_supported_glyph("€") is False
    assert is_supported_glyph("😀") is False
    assert metadata["verification_boundaries"]["actual_cea608_byte_generation"] == "unverified"


def test_runtime_lookup_does_not_normalize_replace_or_drop_source_glyphs() -> None:
    findings = unsupported_glyphs("Café e\u0301 €😀")

    assert findings == (
        UnsupportedGlyph(position=6, character="́", code_point=0x0301),
        UnsupportedGlyph(position=8, character="€", code_point=0x20AC),
        UnsupportedGlyph(position=9, character="😀", code_point=0x1F600),
    )
    assert findings[0].code_point_label == "U+0301"
    assert findings[1].code_point_label == "U+20AC"


@pytest.mark.parametrize("value", ["", "ab", "e\u0301", "\ud800"])
def test_runtime_lookup_requires_exactly_one_unicode_scalar(value: str) -> None:
    with pytest.raises(ValueError, match="Unicode scalar"):
        is_supported_glyph(value)


def test_runtime_lookup_rejects_non_text_inputs() -> None:
    with pytest.raises(TypeError, match="glyph must be a str"):
        is_supported_glyph(None)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="text must be a str"):
        unsupported_glyphs(None)  # type: ignore[arg-type]
