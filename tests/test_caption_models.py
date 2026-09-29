"""P01 contract tests: no composition, timing search, or rendering lives here."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from elevenlabs_helper.engine.captions import (
    CAPTION_SCHEMA_VERSION,
    CONTRACT_EXAMPLES,
    HOUSE_ENGLISH_V1,
    CaptionDocument,
    CaptionEvent,
    CaptionExportOptions,
    CaptionExportPolicy,
    CaptionIssueSeverity,
    CaptionQCIssue,
    CaptionQCReport,
    CaptionSource,
    CaptionSourceToken,
    CaptionTimingMode,
    canonical_json,
    get_caption_profile,
)


def _event() -> CaptionEvent:
    return CaptionEvent(
        start=0.0,
        end=1.25,
        authored_lines=("Hello there.",),
        source_token_indices=(3, 4),
        timing_mode=CaptionTimingMode.HOUSE,
    )


def _document() -> CaptionDocument:
    return CaptionDocument(
        profile=HOUSE_ENGLISH_V1,
        options=CaptionExportOptions(export_policy=CaptionExportPolicy.DRAFT),
        source_hash="source-abc",
        speaker_overlay_hash="overlay-none",
        events=(_event(),),
    )


def test_house_english_v1_freezes_documented_limits_and_text_only_scope() -> None:
    profile = get_caption_profile("house-english-v1", "1")

    assert profile is HOUSE_ENGLISH_V1
    assert profile.language_scope == ("en",)
    assert (profile.max_chars_per_line, profile.max_lines_per_event) == (32, 2)
    assert (profile.cps_target, profile.cps_warning) == (17.0, 20.0)
    assert (profile.min_duration_secs, profile.max_duration_secs) == (1.0, 7.0)
    assert profile.styling_allowed is False
    assert profile.glyph_repertoire_version == (
        "cea608-libcaption-v0.8-e8b6261090eb3f2012427cc6b151c923f82453db"
    )


def test_models_are_strict_and_unknown_schema_or_profile_fails() -> None:
    with pytest.raises(ValidationError):
        CaptionExportOptions.model_validate({"timing_mode": "house", "unexpected": True})
    with pytest.raises(ValidationError):
        CaptionExportOptions.model_validate({"timing_mode": "house", "schema_version": "99"})
    with pytest.raises(ValidationError):
        CaptionSourceToken.model_validate({"source_word_index": "0", "text": "word"})
    with pytest.raises(ValueError, match="unknown caption profile"):
        get_caption_profile("external-file-profile")


def test_event_requires_finite_ordered_renderable_times_and_source_references() -> None:
    for start, end in ((float("nan"), 1.0), (0.0, float("inf")), (-0.1, 1.0), (1.0, 1.0)):
        with pytest.raises(ValidationError):
            CaptionEvent(
                start=start,
                end=end,
                authored_lines=("Text",),
                source_token_indices=(0,),
                timing_mode=CaptionTimingMode.SOURCE,
            )
    with pytest.raises(ValidationError):
        CaptionEvent(
            start=0.0,
            end=1.0,
            authored_lines=("Text",),
            source_token_indices=(),
            timing_mode=CaptionTimingMode.SOURCE,
        )


def test_nonfinite_source_time_becomes_a_json_safe_diagnostic() -> None:
    token = CaptionSourceToken(source_word_index=7, text="Hello", original_start=float("nan"), original_end=float("inf"))
    payload = token.model_dump(mode="json")

    assert payload["original_start"] is None
    assert payload["original_end"] is None
    assert [(item["field_name"], item["representation"]) for item in payload["invalid_numeric_values"]] == [
        ("original_start", "NaN"),
        ("original_end", "Infinity"),
    ]
    serialized = token.model_dump_json()
    assert '"original_start":NaN' not in serialized
    assert '"original_end":Infinity' not in serialized
    assert json.loads(serialized)["invalid_numeric_values"][0]["reason"] == "non_finite"


def test_hashes_and_ids_are_deterministic_and_exclude_operational_time() -> None:
    first = _document()
    second = _document()
    assert first.events[0].event_id == second.events[0].event_id
    assert first.document_hash == second.document_hash
    assert canonical_json({"source": "same", "written_at": "tomorrow"}) == canonical_json(
        {"source": "same", "written_at": "yesterday"}
    )


def test_sidecar_models_round_trip_and_source_data_is_immutable() -> None:
    source = CaptionSource(tokens=(CaptionSourceToken(source_word_index=0, text="Hi"),))
    document = _document()
    report = CaptionQCReport(
        options=document.options,
        document_hash=document.document_hash,
        findings=(
            CaptionQCIssue(
                rule_id="CPS_MAX",
                severity=CaptionIssueSeverity.WARNING,
                event_id=document.events[0].event_id,
                source_token_indices=(3, 4),
                actual_value=17.1,
                threshold=17.0,
                message="Reading speed is above the target.",
            ),
        ),
    )

    assert CaptionSource.model_validate_json(source.model_dump_json()) == source
    assert CaptionDocument.model_validate_json(document.model_dump_json()) == document
    assert CaptionQCReport.model_validate_json(report.model_dump_json()) == report
    assert report.severity_counts == {"info": 0, "warning": 1, "failure": 0, "blocker": 0}
    with pytest.raises(ValidationError):
        source.tokens = ()  # type: ignore[misc]


def test_contract_examples_are_standard_json_and_versioned() -> None:
    assert json.loads(json.dumps(CONTRACT_EXAMPLES, allow_nan=False))["options"]["schema_version"] == CAPTION_SCHEMA_VERSION
    invalid = CONTRACT_EXAMPLES["invalid_timestamp"]
    assert invalid["invalid_numeric_values"] == [
        {"field_name": "original_start", "representation": "NaN", "reason": "non_finite"}
    ]
