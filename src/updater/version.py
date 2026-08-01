"""
Single source of truth for "what version am I".

Bumping this one string is the whole release checklist on the version
side; the build workflow refuses to publish a tag that disagrees with it.
"""
from __future__ import annotations

__version__ = "2.3.3"


def parse(version_string: str) -> tuple[int, ...]:
    """Turn 'v1.2.3' / '1.2.3' / '1.2' into a comparable tuple (1, 2, 3).

    Lenient because GitHub tag names vary. Anything unparseable becomes
    (0,), which sorts lowest - a malformed tag should look "not newer",
    not crash the update check.
    """
    if not version_string:
        return (0,)

    s = version_string.strip()
    if s.lower().startswith("v"):
        s = s[1:]

    # Keep only the leading dotted-integer run, e.g. "1.2.0-beta.1" -> "1.2.0"
    parts: list[int] = []
    for chunk in s.split("."):
        digits = ""
        for ch in chunk:
            if ch.isdigit():
                digits += ch
            else:
                break
        if not digits:
            break
        parts.append(int(digits))

    return tuple(parts) if parts else (0,)


def get_installed_version() -> str:
    """The version of the app currently running."""
    return __version__
