"""
Single source of truth for "what version am I".

Every other updater module (and anything in the rest of the app that
wants to show a version number, e.g. an About dialog) should import
`__version__` from here rather than hardcoding it - bumping this one
string is the entire release checklist on the version side.
"""
from __future__ import annotations

__version__ = "1.0.1"


def parse(version_string: str) -> tuple[int, ...]:
    """Turn 'v1.2.3' / '1.2.3' / '1.2' into a comparable tuple (1, 2, 3).

    Deliberately lenient: GitHub tag names vary (`v1.2.0`, `1.2.0`,
    `release-1.2.0`), so this strips a leading 'v' and any non-numeric
    prefix, then takes the longest run of dot-separated integers it can
    find. Anything it truly can't parse becomes (0,), which sorts lowest
    rather than raising - a malformed tag should never crash the update
    check, it should just look "not newer".
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
    """The version of the app currently running.

    A thin wrapper (rather than importing `__version__` everywhere
    directly) so this is the one place that would change if version
    info ever moves to a build-time-generated file instead of a
    hardcoded constant.
    """
    return __version__
