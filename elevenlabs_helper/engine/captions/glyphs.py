"""Exact Unicode membership lookup for the pinned libcaption CEA-608 repertoire.

This is deliberately a repertoire lookup only.  It does not select CEA-608
bytes, emit control codes, or establish encoder, transport, or player support.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
import json
from types import MappingProxyType
from typing import Any, Mapping


_DATA_FILE = "cea608_repertoire_v1.json"
_EXPECTED_SCHEMA_ID = "elevenlabs-helper.caption.cea608-repertoire"
_EXPECTED_SCHEMA_VERSION = "1.0.0"
_EXPECTED_STATUS = "verified_repertoire_lookup_only"
_EXPECTED_REPERTOIRE_ID = "cea608-libcaption-v0.8-e8b6261090eb3f2012427cc6b151c923f82453db"


@dataclass(frozen=True)
class UnsupportedGlyph:
    """An exact, unmodified character absent from the pinned repertoire.

    ``position`` is a zero-based Unicode code-point index in the original text.
    ``code_point`` is the numeric scalar value; ``code_point_label`` is provided
    for human-readable QC output.
    """

    position: int
    character: str
    code_point: int

    @property
    def code_point_label(self) -> str:
        return f"U+{self.code_point:04X}"


@dataclass(frozen=True)
class _Repertoire:
    glyphs: frozenset[str]
    metadata: Mapping[str, Any]


def _freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


def _require_scalar(char: str) -> None:
    if not isinstance(char, str):
        raise TypeError("glyph must be a str containing exactly one Unicode scalar")
    if len(char) != 1 or 0xD800 <= ord(char) <= 0xDFFF:
        raise ValueError("glyph must contain exactly one Unicode scalar")


def _load_data() -> dict[str, Any]:
    try:
        resource = resources.files(__package__).joinpath("data", _DATA_FILE)
        with resource.open("r", encoding="utf-8") as source:
            value = json.load(source)
    except (FileNotFoundError, json.JSONDecodeError, OSError) as exc:
        raise RuntimeError(f"cannot load pinned caption repertoire {_DATA_FILE}") from exc
    if not isinstance(value, dict):
        raise RuntimeError("caption repertoire root must be a JSON object")
    return value


def _validate_data(data: Mapping[str, Any]) -> frozenset[str]:
    expected = {
        "schema_id": _EXPECTED_SCHEMA_ID,
        "schema_version": _EXPECTED_SCHEMA_VERSION,
        "status": _EXPECTED_STATUS,
        "repertoire_id": _EXPECTED_REPERTOIRE_ID,
    }
    for key, value in expected.items():
        if data.get(key) != value:
            raise RuntimeError(f"caption repertoire has unexpected {key}: {data.get(key)!r}")
    if data.get("data_version") != _EXPECTED_SCHEMA_VERSION:
        raise RuntimeError(f"caption repertoire has unexpected data_version: {data.get('data_version')!r}")

    character_sets = data.get("character_sets")
    if not isinstance(character_sets, list) or not character_sets:
        raise RuntimeError("caption repertoire requires a non-empty character_sets array")

    glyphs: set[str] = set()
    set_ids: set[str] = set()
    for index, character_set in enumerate(character_sets):
        if not isinstance(character_set, dict):
            raise RuntimeError(f"caption repertoire character_sets[{index}] must be an object")
        set_id = character_set.get("id")
        set_glyphs = character_set.get("glyphs")
        if not isinstance(set_id, str) or not set_id or set_id in set_ids:
            raise RuntimeError(f"caption repertoire character_sets[{index}] has an invalid or duplicate id")
        if not isinstance(set_glyphs, list) or not set_glyphs:
            raise RuntimeError(f"caption repertoire character_sets[{index}] requires glyphs")
        set_ids.add(set_id)
        for glyph in set_glyphs:
            try:
                _require_scalar(glyph)
            except (TypeError, ValueError) as exc:
                raise RuntimeError(f"caption repertoire set {set_id!r} contains a non-scalar glyph") from exc
            glyphs.add(glyph)
    return frozenset(glyphs)


@lru_cache(maxsize=1)
def _repertoire() -> _Repertoire:
    data = _load_data()
    glyphs = _validate_data(data)
    # Glyph membership is held separately as an immutable set.  Metadata keeps
    # the pinned provenance/boundary statements but not a mutable JSON object.
    metadata = {key: value for key, value in data.items() if key != "character_sets"}
    metadata["character_set_ids"] = tuple(item["id"] for item in data["character_sets"])
    metadata["glyph_count"] = len(glyphs)
    return _Repertoire(glyphs=glyphs, metadata=_freeze(metadata))


def repertoire_metadata() -> Mapping[str, Any]:
    """Return immutable provenance and scope for the pinned membership dataset."""

    return _repertoire().metadata


def is_supported_glyph(char: str) -> bool:
    """Return exact pinned-repertoire membership for one Unicode scalar only."""

    _require_scalar(char)
    return char in _repertoire().glyphs


def unsupported_glyphs(text: str) -> tuple[UnsupportedGlyph, ...]:
    """Return every unsupported source character without normalization or edits."""

    if not isinstance(text, str):
        raise TypeError("text must be a str")
    glyphs = _repertoire().glyphs
    return tuple(
        UnsupportedGlyph(position=index, character=char, code_point=ord(char))
        for index, char in enumerate(text)
        if char not in glyphs
    )
