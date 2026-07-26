"""
GitHub Releases API client.

Deliberately talks to exactly one endpoint:

    GET /repos/{owner}/{repo}/releases/latest

This is the "latest non-prerelease, non-draft release" endpoint - it
will never surface a commit, a branch, or a draft/prerelease unless we
explicitly ask the /releases list endpoint for one (which we don't).
That's what keeps this "only check GitHub Releases" rather than
"check GitHub for changes".

Uses stdlib `urllib` instead of `requests` so this doesn't add a new
dependency to requirements.txt for a handful of GET requests.
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass, field

logger = logging.getLogger("meet_automation")

API_BASE = "https://api.github.com"
REQUEST_TIMEOUT_SECONDS = 10


@dataclass
class ReleaseAsset:
    name: str
    download_url: str
    size_bytes: int
    content_type: str = ""


@dataclass
class ReleaseInfo:
    tag: str
    name: str
    notes: str
    html_url: str
    published_at: str
    assets: list[ReleaseAsset] = field(default_factory=list)
    prerelease: bool = False

    def pick_asset(self, name_contains: str | None = None) -> ReleaseAsset | None:
        """Pick the asset meant for this platform/build.

        `name_contains` is a substring match (case-insensitive) against
        the asset filename - e.g. "windows" or "EarlyBird-Setup" or
        "EarlyBird.exe", whatever convention the release assets use.
        Falls back to the first asset if there's only one, so a repo
        that ships a single .exe per release doesn't need any filtering.
        """
        if not self.assets:
            return None
        if name_contains:
            needle = name_contains.lower()
            for asset in self.assets:
                if needle in asset.name.lower():
                    return asset
        if len(self.assets) == 1:
            return self.assets[0]
        return None


class GitHubReleaseError(Exception):
    """Raised for network/API failures - callers should treat this as
    'couldn't check right now', not 'no update available'."""


def get_latest_release(repo_owner: str, repo_name: str) -> ReleaseInfo | None:
    """Fetch the latest published (non-draft, non-prerelease) release.

    Returns None if the repo has no releases yet (GitHub returns 404
    for /releases/latest in that case - that's a normal state, not an
    error). Raises GitHubReleaseError for anything else that goes wrong
    (network down, rate limited, malformed response) so the caller can
    distinguish "no releases" from "couldn't check".
    """
    url = f"{API_BASE}/repos/{repo_owner}/{repo_name}/releases/latest"
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "EarlyBird-Updater",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            logger.info("No GitHub releases found for %s/%s", repo_owner, repo_name)
            return None
        raise GitHubReleaseError(f"GitHub API returned HTTP {e.code}") from e
    except urllib.error.URLError as e:
        raise GitHubReleaseError(f"Could not reach GitHub ({e.reason})") from e
    except (TimeoutError, json.JSONDecodeError) as e:
        raise GitHubReleaseError(f"Bad response from GitHub ({e})") from e

    return _parse_release(payload)


def _parse_release(payload: dict) -> ReleaseInfo:
    assets = [
        ReleaseAsset(
            name=a.get("name", ""),
            download_url=a.get("browser_download_url", ""),
            size_bytes=int(a.get("size", 0)),
            content_type=a.get("content_type", ""),
        )
        for a in payload.get("assets", [])
    ]
    return ReleaseInfo(
        tag=payload.get("tag_name", ""),
        name=payload.get("name") or payload.get("tag_name", ""),
        notes=payload.get("body") or "",
        html_url=payload.get("html_url", ""),
        published_at=payload.get("published_at", ""),
        assets=assets,
        prerelease=bool(payload.get("prerelease", False)),
    )
