"""
Decides "is the latest GitHub Release actually newer than what's
installed" - kept separate from github_release.py so the comparison
logic (and the skipped-version rule) is unit-testable without any
network access.
"""
from __future__ import annotations

from dataclasses import dataclass

from .github_release import ReleaseInfo
from . import version as version_module


@dataclass
class UpdateCheckResult:
    update_available: bool
    current_version: str
    release: ReleaseInfo | None


def is_newer(current_version: str, candidate_tag: str) -> bool:
    return version_module.parse(candidate_tag) > version_module.parse(current_version)


def check(
    release: ReleaseInfo | None,
    current_version: str | None = None,
    skip_prereleases: bool = True,
) -> UpdateCheckResult:
    """Compare `release` (the latest GitHub Release, or None if there
    isn't one yet) against the installed version.

    `skip_prereleases` exists for the future beta channel: today the
    stable channel is the only one wired up, and /releases/latest never
    returns a prerelease anyway, but a beta-channel checker will call
    this same function against a different release (one that *can* be
    a prerelease) with skip_prereleases=False.
    """
    current = current_version or version_module.get_installed_version()

    if release is None:
        return UpdateCheckResult(update_available=False, current_version=current, release=None)

    if skip_prereleases and release.prerelease:
        return UpdateCheckResult(update_available=False, current_version=current, release=None)

    newer = is_newer(current, release.tag)
    return UpdateCheckResult(
        update_available=newer,
        current_version=current,
        release=release if newer else None,
    )
