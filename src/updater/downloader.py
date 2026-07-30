"""
Downloads a release asset to a staging directory and verifies it
arrived intact before anything downstream trusts it.
"""
from __future__ import annotations

import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable

from .github_release import ReleaseAsset
from ..logging_setup import get_logger

logger = get_logger()

REQUEST_TIMEOUT_SECONDS = 30
CHUNK_SIZE = 1024 * 256  # 256 KB

ProgressCallback = Callable[[int, int], None]  # (bytes_downloaded, total_bytes)


class DownloadError(Exception):
    pass


def staging_dir() -> Path:
    """Where downloads live before install: the system temp dir, not the
    install directory, which may need elevation to write and is the very
    thing about to be replaced."""
    path = Path(tempfile.gettempdir()) / "EarlyBird" / "updates"
    path.mkdir(parents=True, exist_ok=True)
    return path


def download_asset(
    asset: ReleaseAsset,
    destination_dir: Path | None = None,
    on_progress: ProgressCallback | None = None,
) -> Path:
    """Download `asset` and return the local path once verified.

    Verification is a size check against what GitHub reported, which
    catches truncated downloads without the release process having to
    publish a checksum file.
    """
    dest_dir = destination_dir or staging_dir()
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / asset.name
    tmp_path = dest_dir / f"{asset.name}.part"

    request = urllib.request.Request(
        asset.download_url,
        headers={"User-Agent": "EarlyBird-Updater"},
    )

    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            total = int(response.headers.get("Content-Length") or asset.size_bytes or 0)
            written = 0
            with open(tmp_path, "wb") as f:
                while True:
                    chunk = response.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    f.write(chunk)
                    written += len(chunk)
                    if on_progress:
                        on_progress(written, total)
    except (urllib.error.URLError, OSError) as e:
        tmp_path.unlink(missing_ok=True)
        raise DownloadError(f"Download failed ({e})") from e

    expected = asset.size_bytes or total
    if expected and written != expected:
        tmp_path.unlink(missing_ok=True)
        raise DownloadError(
            f"Downloaded {written} bytes but expected {expected} - "
            "the file may have been truncated, retry the download"
        )

    tmp_path.replace(dest_path)
    logger.info("Downloaded update asset '%s' (%d bytes) to %s", asset.name, written, dest_path)
    return dest_path
