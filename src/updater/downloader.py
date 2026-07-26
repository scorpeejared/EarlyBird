"""
Downloads a release asset to a staging directory and verifies it
arrived intact before anything downstream trusts it.
"""
from __future__ import annotations

import logging
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable

from .github_release import ReleaseAsset

logger = logging.getLogger("meet_automation")

REQUEST_TIMEOUT_SECONDS = 30
CHUNK_SIZE = 1024 * 256  # 256 KB

ProgressCallback = Callable[[int, int], None]  # (bytes_downloaded, total_bytes)


class DownloadError(Exception):
    pass


def staging_dir() -> Path:
    """Where in-progress/completed downloads live before install.

    Uses the system temp dir under a namespaced subfolder rather than
    anything inside the app's own install directory, since on Windows
    the install directory may not be writable without elevation and
    (more importantly) is the thing about to be replaced.
    """
    path = Path(tempfile.gettempdir()) / "EarlyBird" / "updates"
    path.mkdir(parents=True, exist_ok=True)
    return path


def download_asset(
    asset: ReleaseAsset,
    destination_dir: Path | None = None,
    on_progress: ProgressCallback | None = None,
) -> Path:
    """Download `asset` and return the local path once fully verified.

    Verification here is a size check against what GitHub reported for
    the asset (Content-Length should agree, and the bytes actually
    written should match too) - cheap, catches truncated/interrupted
    downloads, and doesn't require the release process to also publish
    a checksum file (release signature verification is listed as a
    later addition; this is intentionally the minimal honest check
    that fits today's release process).
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


def cleanup_staging() -> None:
    """Remove any leftover files from previous update attempts.

    Called after a successful install and also opportunistically on
    startup, so a crashed/interrupted update doesn't leave partial
    downloads accumulating in temp forever.
    """
    import shutil

    path = staging_dir()
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)
