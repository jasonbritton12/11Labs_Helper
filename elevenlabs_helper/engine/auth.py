"""API-key resolution.

Order of precedence:
1. macOS Keychain (desktop app stores the user's key here).
2. ELEVENLABS_API_KEY environment variable (headless / SDVI-Rally / CI).

The ``keyring`` import is optional so the engine still runs in slim containers
that only set the env var.
"""

from __future__ import annotations

import os
import sys

KEYRING_SERVICE = "ElevenLabsHelper"
KEYRING_USERNAME = "elevenlabs_api_key"
ENV_VAR = "ELEVENLABS_API_KEY"


def _pin_macos_backend() -> None:
    """On macOS, pin the secure Keychain backend so keyring never silently falls
    back to an insecure plaintext store."""
    if sys.platform != "darwin":
        return
    try:
        import keyring  # noqa: PLC0415
        from keyring.backends import macOS  # noqa: PLC0415

        if not isinstance(keyring.get_keyring(), macOS.Keyring):
            keyring.set_keyring(macOS.Keyring())
    except Exception:
        pass


class MissingApiKeyError(RuntimeError):
    """Raised when no API key can be found in the Keychain or environment."""


def _keyring_get() -> str | None:
    try:
        import keyring  # noqa: PLC0415 - optional dependency
    except Exception:
        return None
    _pin_macos_backend()
    try:
        return keyring.get_password(KEYRING_SERVICE, KEYRING_USERNAME)
    except Exception:
        return None


def get_api_key(explicit: str | None = None) -> str:
    """Return the API key, raising :class:`MissingApiKeyError` if none is available."""
    key = explicit or os.environ.get(ENV_VAR) or _keyring_get()
    if not key:
        raise MissingApiKeyError(
            "No ElevenLabs API key found. Add one in Settings (stored in the macOS "
            f"Keychain) or set the {ENV_VAR} environment variable."
        )
    return key.strip()


def has_api_key() -> bool:
    try:
        get_api_key()
        return True
    except MissingApiKeyError:
        return False


def set_api_key(key: str) -> None:
    """Store the key in the macOS Keychain (desktop use)."""
    import keyring  # noqa: PLC0415

    _pin_macos_backend()
    keyring.set_password(KEYRING_SERVICE, KEYRING_USERNAME, key.strip())


def clear_api_key() -> None:
    try:
        import keyring  # noqa: PLC0415

        keyring.delete_password(KEYRING_SERVICE, KEYRING_USERNAME)
    except Exception:
        pass
