"""Versioned, deterministic contracts for caption authoring.

This module deliberately contains no segmentation, timing search, rendering, or
file I/O.  It is the stable boundary shared by those later stages.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from decimal import Decimal, InvalidOperation
from datetime import datetime, timezone
from enum import Enum
from math import gcd
from typing import Any, ClassVar, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator, model_validator


CAPTION_SCHEMA_VERSION = "1"
CAPTION_ALGORITHM_VERSION = "caption-authoring-v1"


class _CaptionModel(BaseModel):
    """Strict, immutable base for sidecar-safe caption values."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    @model_validator(mode="before")
    @classmethod
    def _ignore_derived_hashes_on_read(cls, value: Any) -> Any:
        """Accept our own JSON sidecars while recomputing derived hash fields."""

        if not isinstance(value, Mapping):
            return value
        data = dict(value)
        for field_name in (
            "profile_hash",
            "source_hash",
            "context_hash",
            "document_hash",
            "report_hash",
            "severity_counts",
            "measurement_hash",
            "grid_hash",
            "projection_id",
        ):
            # These are computed from the remaining serialized contract.  They
            # must never be trusted from a sidecar supplied by a later process.
            if field_name in cls.model_computed_fields:
                data.pop(field_name, None)
        return data


class CaptionTimingMode(str, Enum):
    HOUSE = "house"
    SOURCE = "source"


class CaptionFrameAlignment(str, Enum):
    FLOOR_START_CEIL_END = "floor_start_ceil_end"
    NONE = "none"


class CaptionExportPolicy(str, Enum):
    DRAFT = "draft"
    STRICT = "strict"


class CaptionRenderingDisposition(str, Enum):
    WRITTEN = "written"
    DRAFT = "draft"
    BLOCKED = "blocked"
    NOT_REQUESTED = "not_requested"


class CaptionContentKind(str, Enum):
    WORD = "word"
    AUDIO_EVENT = "audio_event"


class CaptionIssueSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    FAILURE = "failure"
    BLOCKER = "blocker"


class CaptionTechnicalStatus(str, Enum):
    PASS = "pass"
    WARNING = "warning"
    FAILED = "failed"
    BLOCKED = "blocked"
    NOT_EVALUATED = "not_evaluated"


class CaptionEditorialCoverage(str, Enum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    NOT_EVALUATED = "not_evaluated"
    APPROVAL_REQUIRED = "approval_required"


class CaptionExceptionState(str, Enum):
    NONE = "none"
    APPROVAL_REQUIRED = "approval_required"
    APPROVED = "approved"


def _canonical_value(value: Any, *, exclude_operational: bool = True) -> Any:
    """Return a JSON value with no non-standard floating point literals.

    Operational timestamps intentionally do not participate in content hashes.
    Caption models do not currently write those fields, but this makes the
    hashing contract safe for future provenance extensions.
    """

    if isinstance(value, BaseModel):
        return _canonical_value(value.model_dump(mode="json"), exclude_operational=exclude_operational)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {
            str(key): _canonical_value(item, exclude_operational=exclude_operational)
            for key, item in value.items()
            if not (exclude_operational and str(key) in {"created_at", "generated_at", "written_at", "operational_time"})
        }
    if isinstance(value, (tuple, list)):
        return [_canonical_value(item, exclude_operational=exclude_operational) for item in value]
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("canonical caption JSON cannot contain NaN or infinity")
        return value
    return value


def canonical_json(value: Any, *, exclude_operational: bool = True) -> str:
    """Stable JSON used by every P01 identifier and content hash."""

    return json.dumps(
        _canonical_value(value, exclude_operational=exclude_operational),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def deterministic_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def deterministic_id(prefix: str, value: Any) -> str:
    return f"{prefix}_{deterministic_hash(value)[:24]}"


def _finite(value: float, field_name: str) -> float:
    if not math.isfinite(value):
        raise ValueError(f"{field_name} must be finite")
    return value


def _known_schema(value: str) -> str:
    if value != CAPTION_SCHEMA_VERSION:
        raise ValueError(f"unsupported caption schema version: {value!r}")
    return value


def _json_safe(value: Any) -> Any:
    """Keep diagnostics serializable without silently inventing a number."""

    if isinstance(value, float) and not math.isfinite(value):
        return {
            "kind": "invalid_numeric_value",
            "representation": "NaN" if math.isnan(value) else ("Infinity" if value > 0 else "-Infinity"),
            "reason": "non_finite",
        }
    if isinstance(value, BaseModel):
        return _json_safe(value.model_dump(mode="json"))
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


class InvalidNumericValue(_CaptionModel):
    """A source value that cannot be used to render synchronized captions."""

    field_name: str
    representation: str
    reason: str = "non_finite"


class CaptionExportOptions(_CaptionModel):
    schema_version: str = CAPTION_SCHEMA_VERSION
    timing_mode: CaptionTimingMode = CaptionTimingMode.HOUSE
    profile_id: str = "house-english-v1"
    profile_version: str = "1"
    export_policy: CaptionExportPolicy = CaptionExportPolicy.DRAFT

    @field_validator("schema_version")
    @classmethod
    def _known_options_schema(cls, value: str) -> str:
        return _known_schema(value)

    @field_validator("profile_id", "profile_version")
    @classmethod
    def _nonempty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value


class CaptionDestinationOverride(_CaptionModel):
    destination_id: str
    version: str
    rationale: str
    max_chars_per_line: int | None = None
    max_lines_per_event: int | None = None
    max_cps_hard: float | None = None
    min_duration_secs: float | None = None
    max_duration_secs: float | None = None

    @field_validator("max_cps_hard", "min_duration_secs", "max_duration_secs")
    @classmethod
    def _finite_optional(cls, value: float | None, info: Any) -> float | None:
        return None if value is None else _finite(value, info.field_name)


class CaptionProfile(_CaptionModel):
    schema_version: str = CAPTION_SCHEMA_VERSION
    profile_id: str
    profile_version: str
    name: str
    language_scope: tuple[str, ...]
    max_chars_per_line: int
    max_lines_per_event: int
    cps_target: float
    cps_warning: float
    min_duration_secs: float
    max_duration_secs: float
    glyph_repertoire_version: str
    styling_allowed: bool = False
    destination_overrides: tuple[CaptionDestinationOverride, ...] = ()

    @field_validator("schema_version")
    @classmethod
    def _known_profile_schema(cls, value: str) -> str:
        return _known_schema(value)

    @field_validator("language_scope", "destination_overrides", mode="before")
    @classmethod
    def _tuple_fields(cls, value: Any) -> tuple[Any, ...]:
        return tuple(value)

    @model_validator(mode="after")
    def _valid_limits(self) -> "CaptionProfile":
        if not self.profile_id or not self.profile_version or not self.name:
            raise ValueError("profile identity fields must not be blank")
        if not self.language_scope:
            raise ValueError("language_scope must not be empty")
        if self.max_chars_per_line <= 0 or self.max_lines_per_event <= 0:
            raise ValueError("caption capacity limits must be positive")
        if self.cps_target <= 0 or self.cps_warning < self.cps_target:
            raise ValueError("CPS limits must be positive and ordered")
        if self.min_duration_secs <= 0 or self.max_duration_secs < self.min_duration_secs:
            raise ValueError("duration limits must be positive and ordered")
        if self.styling_allowed:
            raise ValueError("P01 profiles must remain text-and-timing-only")
        return self

    @computed_field(return_type=str)
    @property
    def profile_hash(self) -> str:
        return deterministic_hash(self.model_dump(exclude={"profile_hash"}))


class CaptionBaselineCue(_CaptionModel):
    index: int = Field(ge=1)
    text: str
    start: float | None = None
    end: float | None = None
    speaker_id: str | None = None
    is_audio_event: bool = False
    source_word_indices: tuple[int, ...] = ()

    @field_validator("source_word_indices", mode="before")
    @classmethod
    def _tuple_indices(cls, value: Any) -> tuple[Any, ...]:
        return tuple(value)

    @field_validator("start", "end")
    @classmethod
    def _finite_optional(cls, value: float | None, info: Any) -> float | None:
        return None if value is None else _finite(value, info.field_name)


class CaptionSourceToken(_CaptionModel):
    """One original result token, retaining source indices even when invalid."""

    source_word_index: int = Field(ge=0)
    canonical_cue_index: int | None = Field(default=None, ge=1)
    text: str
    content_kind: CaptionContentKind = CaptionContentKind.WORD
    speaker_id: str | None = None
    original_start: float | None = None
    original_end: float | None = None
    invalid_numeric_values: tuple[InvalidNumericValue, ...] = ()

    @field_validator("invalid_numeric_values", mode="before")
    @classmethod
    def _tuple_invalid_values(cls, value: Any) -> tuple[Any, ...]:
        return tuple(value)

    @model_validator(mode="before")
    @classmethod
    def _preserve_nonfinite_diagnostics(cls, value: Any) -> Any:
        if not isinstance(value, Mapping):
            return value
        data = dict(value)
        existing = list(data.get("invalid_numeric_values") or ())
        # Accept source adapters that naturally call these fields start/end too.
        for external, field_name in (("start", "original_start"), ("end", "original_end")):
            if field_name not in data and external in data:
                data[field_name] = data.pop(external)
        for field_name in ("original_start", "original_end"):
            raw = data.get(field_name)
            if isinstance(raw, float) and not math.isfinite(raw):
                existing.append(
                    InvalidNumericValue(
                        field_name=field_name,
                        representation="NaN" if math.isnan(raw) else ("Infinity" if raw > 0 else "-Infinity"),
                    )
                )
                data[field_name] = None
        data["invalid_numeric_values"] = tuple(existing)
        return data

    @field_validator("original_start", "original_end")
    @classmethod
    def _finite_optional(cls, value: float | None, info: Any) -> float | None:
        return None if value is None else _finite(value, info.field_name)


class CaptionSource(_CaptionModel):
    schema_version: str = CAPTION_SCHEMA_VERSION
    tokens: tuple[CaptionSourceToken, ...] = ()
    baseline_cues: tuple[CaptionBaselineCue, ...] = ()
    speaker_overlay_hash: str = ""
    language_code: str | None = None
    duration_secs: float | None = None

    @field_validator("schema_version")
    @classmethod
    def _known_source_schema(cls, value: str) -> str:
        return _known_schema(value)

    @field_validator("tokens", "baseline_cues", mode="before")
    @classmethod
    def _tuple_fields(cls, value: Any) -> tuple[Any, ...]:
        return tuple(value)

    @field_validator("duration_secs")
    @classmethod
    def _finite_duration(cls, value: float | None) -> float | None:
        return None if value is None else _finite(value, "duration_secs")

    @computed_field(return_type=str)
    @property
    def source_hash(self) -> str:
        # Speaker-edit identity is recorded and hashed separately so later
        # packets can distinguish an unchanged source from a changed overlay.
        return deterministic_hash(self.model_dump(exclude={"source_hash", "speaker_overlay_hash"}))


MAX_DECIMAL_LEXEME_LENGTH = 256
MAX_DECIMAL_EXPONENT_ABS = 10_000
MAX_RATIONAL_COMPONENT_BITS = 16_384
_DECIMAL_LEXEME = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$")


def _reduced_pair(numerator: int, denominator: int) -> tuple[int, int]:
    if denominator <= 0:
        raise ValueError("denominator must be positive")
    if any(abs(component).bit_length() > MAX_RATIONAL_COMPONENT_BITS for component in (numerator, denominator)):
        raise ValueError("rational component exceeds the exact-time size limit")
    common = gcd(numerator, denominator)
    reduced = numerator // common, denominator // common
    if any(abs(component).bit_length() > MAX_RATIONAL_COMPONENT_BITS for component in reduced):
        raise ValueError("rational component exceeds the exact-time size limit")
    return reduced


def _rational_identity(value: "RationalTime | CaptionFrameRate") -> dict[str, str]:
    """Canonical exact identity; JSON numbers never become float material."""

    return {"numerator": str(value.numerator), "denominator": str(value.denominator)}


class RationalTime(_CaptionModel):
    """An exact reduced media time in seconds."""

    numerator: int
    denominator: int = Field(gt=0)

    @model_validator(mode="after")
    def _reduce(self) -> "RationalTime":
        numerator, denominator = _reduced_pair(self.numerator, self.denominator)
        object.__setattr__(self, "numerator", numerator)
        object.__setattr__(self, "denominator", denominator)
        return self

    @classmethod
    def from_decimal(cls, lexeme: str) -> "RationalTime":
        """Parse a finite decimal lexeme without passing through binary float."""

        if not isinstance(lexeme, str) or not lexeme or lexeme != lexeme.strip():
            raise ValueError("decimal time must be a non-empty, unpadded string")
        if len(lexeme) > MAX_DECIMAL_LEXEME_LENGTH or _DECIMAL_LEXEME.fullmatch(lexeme) is None:
            raise ValueError("malformed or unbounded decimal time")
        try:
            value = Decimal(lexeme)
            if (
                not value.is_finite()
                or abs(value.adjusted()) > MAX_DECIMAL_EXPONENT_ABS
                or abs(value.as_tuple().exponent) > MAX_DECIMAL_EXPONENT_ABS
            ):
                raise ValueError("decimal time must be finite and bounded")
            numerator, denominator = value.as_integer_ratio()
        except (InvalidOperation, OverflowError, ValueError) as exc:
            raise ValueError("malformed or unbounded decimal time") from exc
        return cls(numerator=numerator, denominator=denominator)


class CaptionFrameRate(_CaptionModel):
    numerator: int = Field(gt=0)
    denominator: int = Field(gt=0)


class FrameGrid(_CaptionModel):
    frame_rate: CaptionFrameRate
    origin_media_time: RationalTime = Field(default_factory=lambda: RationalTime(numerator=0, denominator=1))
    alignment: CaptionFrameAlignment

    @model_validator(mode="after")
    def _normalize_grid_rate(self) -> "FrameGrid":
        numerator, denominator = _reduced_pair(self.frame_rate.numerator, self.frame_rate.denominator)
        if (numerator, denominator) != (self.frame_rate.numerator, self.frame_rate.denominator):
            object.__setattr__(
                self,
                "frame_rate",
                CaptionFrameRate(numerator=numerator, denominator=denominator),
            )
        return self

    @computed_field(return_type=str)
    @property
    def grid_hash(self) -> str:
        return deterministic_hash(
            {
                "frame_rate": _rational_identity(self.frame_rate),
                "origin_media_time": _rational_identity(self.origin_media_time),
                "alignment": self.alignment.value,
            }
        )


class TimecodeLabelContext(_CaptionModel):
    """Data-only timecode request; C4 F1 deliberately supplies no label algorithm."""

    nominal_fps: int = Field(gt=0)
    drop_frame: bool
    mapping_id: str | None = None
    mapping_verified: bool = False

    @model_validator(mode="after")
    def _drop_frame_is_unverified(self) -> "TimecodeLabelContext":
        if self.mapping_verified:
            raise ValueError("timecode-label mappings remain unverified in C4 F1")
        return self


class TimecodeLabel(_CaptionModel):
    """A validated label value only; conversion/generation remains unsupported."""

    hours: int = Field(ge=0)
    minutes: int = Field(ge=0, lt=60)
    seconds: int = Field(ge=0, lt=60)
    frame: int = Field(ge=0)
    nominal_fps: int = Field(gt=0)
    drop_frame: bool

    @model_validator(mode="after")
    def _frame_within_nominal_rate(self) -> "TimecodeLabel":
        if self.frame >= self.nominal_fps:
            raise ValueError("timecode frame must be less than nominal_fps")
        return self


class FrameProjection(_CaptionModel):
    event_id: str
    start_frame: int
    end_frame_exclusive: int
    original_start: RationalTime
    original_end: RationalTime
    projected_start: RationalTime
    projected_end: RationalTime
    grid_hash: str
    policy_id: str
    policy_version: str
    document_hash: str
    profile_hash: str

    @model_validator(mode="after")
    def _valid_projection(self) -> "FrameProjection":
        for field_name in ("event_id", "grid_hash", "policy_id", "policy_version", "document_hash", "profile_hash"):
            if not getattr(self, field_name).strip():
                raise ValueError(f"{field_name} must not be blank")
        if (
            self.original_end.numerator * self.original_start.denominator
            <= self.original_start.numerator * self.original_end.denominator
        ):
            raise ValueError("original frame interval must be non-empty")
        if self.end_frame_exclusive <= self.start_frame:
            raise ValueError("projected frame interval must be non-empty")
        if (
            self.projected_end.numerator * self.projected_start.denominator
            <= self.projected_start.numerator * self.projected_end.denominator
        ):
            raise ValueError("projected media interval must be non-empty")
        return self

    @computed_field(return_type=str)
    @property
    def projection_id(self) -> str:
        identity = {
            "event_id": self.event_id,
            "original_start": _rational_identity(self.original_start),
            "original_end": _rational_identity(self.original_end),
            "grid_hash": self.grid_hash,
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "document_hash": self.document_hash,
            "profile_hash": self.profile_hash,
        }
        return deterministic_id("caption_frame_projection", identity)


class CaptionContext(_CaptionModel):
    """Optional program facts.  ``None`` explicitly means unknown/not supplied."""

    duration_secs: float | None = None
    frame_rate: CaptionFrameRate | None = None
    shot_change_secs: tuple[float, ...] | None = None

    @field_validator("duration_secs")
    @classmethod
    def _finite_duration(cls, value: float | None) -> float | None:
        return None if value is None else _finite(value, "duration_secs")

    @field_validator("shot_change_secs", mode="before")
    @classmethod
    def _tuple_shots(cls, value: Any) -> tuple[Any, ...] | None:
        return None if value is None else tuple(value)

    @field_validator("shot_change_secs")
    @classmethod
    def _finite_shots(cls, value: tuple[float, ...] | None) -> tuple[float, ...] | None:
        if value is None:
            return None
        return tuple(_finite(item, "shot_change_secs") for item in value)

    @computed_field(return_type=str)
    @property
    def context_hash(self) -> str:
        return deterministic_hash(self.model_dump(exclude={"context_hash"}))


class CaptionContextV2(CaptionContext):
    """Exact frame context stored beside, rather than inside, the v1 contract."""

    schema_version: Literal["2"] = "2"
    media_time_origin: RationalTime
    frame_grid: FrameGrid
    timecode_label_context: TimecodeLabelContext | None = None

    @model_validator(mode="after")
    def _consistent_exact_grid(self) -> "CaptionContextV2":
        if self.media_time_origin != self.frame_grid.origin_media_time:
            raise ValueError("media_time_origin must equal the frame-grid origin")
        if self.frame_rate is not None and self.frame_rate != self.frame_grid.frame_rate:
            raise ValueError("legacy frame_rate must exactly equal the frame-grid rate")
        return self


class CaptionCharacterRange(_CaptionModel):
    source_word_index: int = Field(ge=0)
    start: int = Field(ge=0)
    end: int = Field(ge=0)

    @model_validator(mode="after")
    def _ordered(self) -> "CaptionCharacterRange":
        if self.end < self.start:
            raise ValueError("character range end must be >= start")
        return self


class CaptionEvent(_CaptionModel):
    event_id: str = ""
    algorithm_version: str = CAPTION_ALGORITHM_VERSION
    start: float
    end: float
    authored_lines: tuple[str, ...]
    source_token_indices: tuple[int, ...]
    source_character_ranges: tuple[CaptionCharacterRange, ...] = ()
    speaker_id: str | None = None
    content_kind: CaptionContentKind = CaptionContentKind.WORD
    timing_mode: CaptionTimingMode

    @field_validator("authored_lines", "source_token_indices", "source_character_ranges", mode="before")
    @classmethod
    def _tuple_fields(cls, value: Any) -> tuple[Any, ...]:
        return tuple(value)

    @field_validator("start", "end")
    @classmethod
    def _finite_event_time(cls, value: float, info: Any) -> float:
        return _finite(value, info.field_name)

    @model_validator(mode="after")
    def _renderable_and_identified(self) -> "CaptionEvent":
        if self.start < 0 or self.end <= self.start:
            raise ValueError("renderable caption event requires 0 <= start < end")
        if not self.authored_lines or any(not line for line in self.authored_lines):
            raise ValueError("renderable caption event requires non-empty authored lines")
        if not self.source_token_indices:
            raise ValueError("renderable caption event requires source token references")
        if not self.event_id:
            object.__setattr__(
                self,
                "event_id",
                deterministic_id(
                    "caption_event",
                    self.model_dump(exclude={"event_id"}),
                ),
            )
        return self


class CaptionEventV2(CaptionEvent):
    """A v2 event with required exact endpoints and v1 compatibility floats."""

    schema_version: Literal["2"] = "2"
    start_time: RationalTime
    end_time: RationalTime

    @model_validator(mode="before")
    @classmethod
    def _link_default_id_to_v1_event(cls, value: Any) -> Any:
        """Use the stable v1 semantic identity for a beside-v1 enrichment."""

        if not isinstance(value, Mapping):
            return value
        data = dict(value)
        if data.get("event_id"):
            return data
        v1_payload = {
            field_name: data[field_name]
            for field_name in CaptionEvent.model_fields
            if field_name != "event_id" and field_name in data
        }
        data["event_id"] = CaptionEvent.model_validate(v1_payload).event_id
        return data

    @model_validator(mode="after")
    def _valid_exact_interval(self) -> "CaptionEventV2":
        if self.start_time.numerator < 0:
            raise ValueError("exact caption start_time must be non-negative")
        if (
            self.end_time.numerator * self.start_time.denominator
            <= self.start_time.numerator * self.end_time.denominator
        ):
            raise ValueError("exact caption event requires start_time < end_time")
        try:
            compatible_start = self.start_time.numerator / self.start_time.denominator
            compatible_end = self.end_time.numerator / self.end_time.denominator
        except OverflowError as exc:
            raise ValueError("exact caption time is outside the compatibility-float range") from exc
        if self.start != compatible_start or self.end != compatible_end:
            raise ValueError("legacy float endpoints contradict exact caption times")
        return self


class CaptionDocument(_CaptionModel):
    schema_version: str = CAPTION_SCHEMA_VERSION
    algorithm_version: str = CAPTION_ALGORITHM_VERSION
    profile: CaptionProfile
    options: CaptionExportOptions
    source_hash: str
    speaker_overlay_hash: str
    context_hash: str | None = None
    events: tuple[CaptionEvent, ...] = ()
    provenance: Mapping[str, Any] = Field(default_factory=dict)

    @field_validator("schema_version")
    @classmethod
    def _known_document_schema(cls, value: str) -> str:
        return _known_schema(value)

    @field_validator("events", mode="before")
    @classmethod
    def _tuple_events(cls, value: Any) -> tuple[Any, ...]:
        return tuple(value)

    @field_validator("provenance", mode="before")
    @classmethod
    def _safe_provenance(cls, value: Any) -> Mapping[str, Any]:
        if not isinstance(value, Mapping):
            raise ValueError("provenance must be an object")
        return _json_safe(value)

    @model_validator(mode="after")
    def _ordered_unique_events(self) -> "CaptionDocument":
        if any(type(event) is not CaptionEvent for event in self.events):
            raise ValueError(
                "exact v2 events must be supplied beside the v1 caption document"
            )
        ids = [event.event_id for event in self.events]
        if len(ids) != len(set(ids)):
            raise ValueError("caption event IDs must be unique")
        if any(left.start > right.start for left, right in zip(self.events, self.events[1:])):
            raise ValueError("caption document events must be ordered by start")
        return self

    @computed_field(return_type=str)
    @property
    def document_hash(self) -> str:
        return deterministic_hash(self.model_dump(exclude={"document_hash"}))


class CaptionQCIssue(_CaptionModel):
    issue_id: str = ""
    rule_id: str
    severity: CaptionIssueSeverity
    event_id: str | None = None
    source_token_indices: tuple[int, ...] = ()
    actual_value: Any = None
    threshold: Any = None
    message: str
    suggested_resolution: str | None = None
    approval_reference: str | None = None

    @field_validator("source_token_indices", mode="before")
    @classmethod
    def _tuple_indices(cls, value: Any) -> tuple[Any, ...]:
        return tuple(value)

    @field_validator("actual_value", "threshold", mode="before")
    @classmethod
    def _safe_diagnostics(cls, value: Any) -> Any:
        return _json_safe(value)

    @model_validator(mode="after")
    def _identified(self) -> "CaptionQCIssue":
        if not self.issue_id:
            object.__setattr__(
                self,
                "issue_id",
                # An approval is an annotation of a measured finding, never part
                # of the finding identity.  This makes exact regeneration match
                # a stored exception without changing the rule's identity.
                deterministic_id(
                    "caption_qc",
                    self.model_dump(exclude={"issue_id", "approval_reference"}),
                ),
            )
        return self

    @computed_field(return_type=str)
    @property
    def measurement_hash(self) -> str:
        """Hash the immutable rule measurement, excluding approval annotation.

        The scope is deliberately narrow and explicit: rule, severity, event and
        source references plus the measured value and threshold.  Narrative text,
        suggested resolutions, approval metadata, and operational times cannot
        make an approval appear stale or current.
        """

        return deterministic_hash(
            {
                "rule_id": self.rule_id,
                "severity": self.severity,
                "event_id": self.event_id,
                "source_token_indices": self.source_token_indices,
                "actual_value": self.actual_value,
                "threshold": self.threshold,
            }
        )


class CaptionApproval(_CaptionModel):
    """A local, issue-scoped exception bound to one exact caption result.

    This is intentionally not an authenticated signature.  It records who made
    a local decision, why, and every deterministic identity needed to verify it
    during later regeneration.
    """

    approval_id: str = ""
    issue_id: str
    rule_id: str
    event_id: str | None = None
    source_token_indices: tuple[int, ...] = ()
    measurement_hash: str
    reason: str
    actor_label: str
    approved_at: datetime
    source_hash: str
    speaker_overlay_hash: str
    profile_id: str
    profile_version: str
    profile_hash: str
    algorithm_version: str
    document_hash: str

    @field_validator("source_token_indices", mode="before")
    @classmethod
    def _approval_indices(cls, value: Any) -> tuple[Any, ...]:
        return tuple(value)

    @field_validator(
        "issue_id", "rule_id", "measurement_hash", "reason", "actor_label",
        "source_hash", "speaker_overlay_hash", "profile_id", "profile_version",
        "profile_hash", "algorithm_version", "document_hash",
    )
    @classmethod
    def _approval_nonempty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("approval fields must not be blank")
        return value

    @field_validator("approved_at", mode="before")
    @classmethod
    def _parse_approval_time(cls, value: Any) -> Any:
        # Strict model validation rejects JSON's ISO timestamp string unless
        # this serialized scalar is explicitly converted at the boundary.
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError as exc:
                raise ValueError("approved_at must be an ISO UTC timestamp") from exc
        return value

    @field_validator("approved_at")
    @classmethod
    def _utc_approval_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timezone.utc.utcoffset(value):
            raise ValueError("approved_at must be an explicit UTC timestamp")
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def _approval_id(self) -> "CaptionApproval":
        if not self.approval_id:
            object.__setattr__(
                self,
                "approval_id",
                deterministic_id("caption_approval", self.model_dump(mode="json", exclude={"approval_id"})),
            )
        return self

    @property
    def material_scope(self) -> tuple[Any, ...]:
        """All technical identity and document bindings for one approval."""

        return (
            self.rule_id,
            self.event_id,
            self.source_token_indices,
            self.measurement_hash,
            self.source_hash,
            self.speaker_overlay_hash,
            self.profile_id,
            self.profile_version,
            self.profile_hash,
            self.algorithm_version,
            self.document_hash,
        )

    @classmethod
    def for_issue(
        cls,
        document: CaptionDocument,
        issue: CaptionQCIssue,
        *,
        reason: str,
        actor_label: str,
        approved_at: datetime | None = None,
    ) -> "CaptionApproval":
        return cls(
            issue_id=issue.issue_id,
            rule_id=issue.rule_id,
            event_id=issue.event_id,
            source_token_indices=issue.source_token_indices,
            measurement_hash=issue.measurement_hash,
            reason=reason,
            actor_label=actor_label,
            approved_at=approved_at or datetime.now(timezone.utc),
            source_hash=document.source_hash,
            speaker_overlay_hash=document.speaker_overlay_hash,
            profile_id=document.profile.profile_id,
            profile_version=document.profile.profile_version,
            profile_hash=document.profile.profile_hash,
            algorithm_version=document.algorithm_version,
            document_hash=document.document_hash,
        )

    def matches(self, document: CaptionDocument, issue: CaptionQCIssue) -> bool:
        return (
            self.rule_id == issue.rule_id
            and self.event_id == issue.event_id
            and self.source_token_indices == issue.source_token_indices
            and self.measurement_hash == issue.measurement_hash
            and self.source_hash == document.source_hash
            and self.speaker_overlay_hash == document.speaker_overlay_hash
            and self.profile_id == document.profile.profile_id
            and self.profile_version == document.profile.profile_version
            and self.profile_hash == document.profile.profile_hash
            and self.algorithm_version == document.algorithm_version
            and self.document_hash == document.document_hash
        )


class CaptionQCReport(_CaptionModel):
    schema_version: str = CAPTION_SCHEMA_VERSION
    findings: tuple[CaptionQCIssue, ...] = ()
    technical_status: CaptionTechnicalStatus = CaptionTechnicalStatus.NOT_EVALUATED
    editorial_coverage: CaptionEditorialCoverage = CaptionEditorialCoverage.NOT_EVALUATED
    exception_state: CaptionExceptionState = CaptionExceptionState.NONE
    options: CaptionExportOptions
    document_hash: str | None = None

    @field_validator("schema_version")
    @classmethod
    def _known_report_schema(cls, value: str) -> str:
        return _known_schema(value)

    @field_validator("findings", mode="before")
    @classmethod
    def _tuple_findings(cls, value: Any) -> tuple[Any, ...]:
        return tuple(value)

    @computed_field(return_type=dict[str, int])
    @property
    def severity_counts(self) -> dict[str, int]:
        return {severity.value: sum(issue.severity is severity for issue in self.findings) for severity in CaptionIssueSeverity}

    @computed_field(return_type=str)
    @property
    def report_hash(self) -> str:
        return deterministic_hash(self.model_dump(exclude={"report_hash"}))


class CaptionInterpretation(_CaptionModel):
    document: CaptionDocument
    report: CaptionQCReport


class ExportResult(_CaptionModel):
    """Structured facts about one output batch; paths contain only written files."""

    paths: Mapping[str, str] = Field(default_factory=dict)
    interpretation: CaptionInterpretation | None = None
    report: CaptionQCReport | None = None
    options: CaptionExportOptions
    disposition: CaptionRenderingDisposition

    @field_validator("paths", mode="before")
    @classmethod
    def _paths_object(cls, value: Any) -> Mapping[str, str]:
        if not isinstance(value, Mapping):
            raise ValueError("paths must be an object")
        return dict(value)


CONTRACT_EXAMPLES: ClassVar[dict[str, Any]] = {
    "options": CaptionExportOptions().model_dump(mode="json"),
    "invalid_timestamp": CaptionSourceToken(
        source_word_index=0,
        text="Hello",
        original_start=float("nan"),
    ).model_dump(mode="json"),
    "source_diagnostic": CaptionQCIssue(
        rule_id="SOURCE_NONFINITE_TIME",
        severity=CaptionIssueSeverity.BLOCKER,
        source_token_indices=(0,),
        actual_value={"field": "original_start", "representation": "NaN"},
        message="Source timestamp is not finite; synchronized caption rendering is blocked.",
        suggested_resolution="Correct the source timestamp before rendering.",
    ).model_dump(mode="json"),
}
