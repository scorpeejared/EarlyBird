"""
GitHub Releases API client.

Talks to exactly one endpoint, GET /repos/{owner}/{repo}/releases/latest,
which only ever returns the latest non-draft, non-prerelease release -
never a commit or branch. Uses stdlib urllib rather than adding
`requests` for a handful of GET requests.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field

from ..logging_setup import get_logger

logger = get_logger()

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
        """Pick the asset meant for this build, by case-insensitive
        substring match on the filename. Falls back to the only asset
        when a release ships just one."""
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
    """Fetch the latest published release.

    None means the repo has no releases yet (a 404 here is normal, not
    an error); GitHubReleaseError means the check itself failed, so
    callers can tell the two apart.
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
