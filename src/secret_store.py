"""
Credential storage, OS keychain first.

An API key is not app configuration, so it never goes in settings.json if the
machine offers somewhere better. On Windows that's Credential Manager via
keyring; macOS Keychain and the Linux Secret Service work the same way.

If no backend is available, storage falls back to settings.json in plaintext
and is_secure() returns False - callers are expected to say so in the UI
rather than quietly pretend the key is protected.
"""
from __future__ import annotations

from . import settings
from .logging_setup import get_logger

logger = get_logger()

SERVICE_NAME = "EarlyBird"

# Keys are stored per provider, so switching between (say) OpenAI and a local
# server doesn't make you re-enter the one you were using before.
def _username(provider_id: str) -> str:
    return f"{provider_id}_api_key"


def _plaintext_setting(provider_id: str) -> str:
    """settings.json key used only when there is no keychain to fall back from."""
    return f"{provider_id}_api_key_plaintext"

_secure: bool | None = None  # cached probe result


def _keyring():
    """The keyring module, or None if it isn't installed."""
    try:
        import keyring
        return keyring
    except ImportError:
        return None


def is_secure() -> bool:
    """True when secrets go to a real OS keychain rather than settings.json.

    Probed once with a throwaway write/read/delete: asking the backend what
    it is doesn't prove it works (a locked or headless keyring imports fine
    and then raises on first use).
    """
    global _secure
    if _secure is not None:
        return _secure

    keyring = _keyring()
    if keyring is None:
        _secure = False
        return _secure

    probe_user = "__earlybird_probe__"
    try:
        keyring.set_password(SERVICE_NAME, probe_user, "probe")
        _secure = keyring.get_password(SERVICE_NAME, probe_user) == "probe"
        keyring.delete_password(SERVICE_NAME, probe_user)
    except Exception as e:  # noqa: BLE001 - any backend failure means "not secure"
        logger.warning(f"No usable keychain ({e}); API key would be stored in plaintext")
        _secure = False
    return _secure


def get_key(provider_id: str) -> str:
    """The stored key for one provider, or "" if there isn't one."""
    if is_secure():
        keyring = _keyring()
        try:
            return keyring.get_password(SERVICE_NAME, _username(provider_id)) or ""
        except Exception as e:  # noqa: BLE001 - treat a read failure as "no key"
            logger.warning(f"Could not read the {provider_id} key from the keychain: {e}")
            return ""
    return str(settings.load().get(_plaintext_setting(provider_id), "") or "")


def save_key(provider_id: str, key: str) -> None:
    key = key.strip()
    if is_secure():
        keyring = _keyring()
        keyring.set_password(SERVICE_NAME, _username(provider_id), key)
        return
    full = settings.load()
    full[_plaintext_setting(provider_id)] = key
    settings.write(full)


def clear_key(provider_id: str) -> None:
    if is_secure():
        keyring = _keyring()
        try:
            keyring.delete_password(SERVICE_NAME, _username(provider_id))
        except Exception:  # noqa: BLE001 - already gone is a fine outcome
            pass
        return
    full = settings.load()
    full.pop(_plaintext_setting(provider_id), None)
    settings.write(full)


def has_key(provider_id: str) -> bool:
    return bool(get_key(provider_id))
