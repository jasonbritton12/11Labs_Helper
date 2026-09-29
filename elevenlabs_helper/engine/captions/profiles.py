"""Built-in caption profiles.

P01 intentionally exposes a small internal registry only.  Destination-specific
profiles require separately verified evidence and are not loaded from arbitrary
files or user JSON.
"""

from __future__ import annotations

from .models import CaptionProfile


HOUSE_ENGLISH_V1 = CaptionProfile(
    profile_id="house-english-v1",
    profile_version="1",
    name="House English v1",
    language_scope=("en",),
    max_chars_per_line=32,
    max_lines_per_event=2,
    cps_target=17.0,
    cps_warning=20.0,
    min_duration_secs=1.0,
    max_duration_secs=7.0,
    # Exact Unicode membership evidence pinned by P01G. This identifies a
    # converter repertoire; it is not a native-608 encoding claim.
    glyph_repertoire_version="cea608-libcaption-v0.8-e8b6261090eb3f2012427cc6b151c923f82453db",
    styling_allowed=False,
)


_PROFILES: dict[tuple[str, str], CaptionProfile] = {
    (HOUSE_ENGLISH_V1.profile_id, HOUSE_ENGLISH_V1.profile_version): HOUSE_ENGLISH_V1,
}


def get_caption_profile(profile_id: str, profile_version: str = "1") -> CaptionProfile:
    """Return an exact built-in profile or fail rather than silently relaxing it."""

    try:
        return _PROFILES[(profile_id, profile_version)]
    except KeyError as exc:
        raise ValueError(f"unknown caption profile: {profile_id!r} version {profile_version!r}") from exc


def available_caption_profiles() -> tuple[CaptionProfile, ...]:
    """Versioned built-in profiles in deterministic identifier order."""

    return tuple(_PROFILES[key] for key in sorted(_PROFILES))
