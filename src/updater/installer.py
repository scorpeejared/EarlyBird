"""
Prepares a downloaded release asset to replace the running app's files.

Windows can't overwrite the .exe of a running process, so nothing here
touches the live install directory - it only unpacks the new build into
a scratch folder. The swap itself happens in updater_launcher.py, from a
separate process, once this one has exited.
"""
from __future__ import annotations

import shutil
import sys
import zipfile
from pathlib import Path

from .. import paths
from ..logging_setup import get_logger

logger = get_logger()


def get_install_dir() -> Path:
    """Directory containing the running app's files: the folder holding
    the .exe when frozen, the project root when running from source.

    Self-update isn't meaningful from source, but keeping this defined
    lets update_manager run check-only there without special cases.
    """
    if paths.is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent.parent


def get_current_exe_path() -> Path:
    if not paths.is_frozen():
        raise RuntimeError("get_current_exe_path() only applies to a packaged (frozen) build")
    return Path(sys.executable).resolve()


class InstallError(Exception):
    pass


def stage_update(downloaded_path: Path) -> Path:
    """Unpack a downloaded asset into a staging folder mirroring the
    final install layout, and return that folder.

    Takes either a .zip of the built app or a raw onefile .exe.
    """
    stage_dir = downloaded_path.parent / "staged"
    if stage_dir.exists():
        shutil.rmtree(stage_dir, ignore_errors=True)
    stage_dir.mkdir(parents=True, exist_ok=True)

    if downloaded_path.suffix.lower() == ".zip":
        try:
            with zipfile.ZipFile(downloaded_path) as zf:
                zf.extractall(stage_dir)
        except zipfile.BadZipFile as e:
            raise InstallError(f"Downloaded update archive is corrupt ({e})") from e
        _flatten_single_wrapper_folder(stage_dir)
    else:
        shutil.copy2(downloaded_path, stage_dir / downloaded_path.name)

    logger.info("Staged update at %s", stage_dir)
    return stage_dir


def _flatten_single_wrapper_folder(stage_dir: Path) -> None:
    """Move a lone top-level folder's contents up one level - the shape
    you get from zipping `dist/EarlyBird/` rather than its contents.
    The updater script looks for exe/_internal directly under stage_dir.
    """
    entries = list(stage_dir.iterdir())
    if len(entries) == 1 and entries[0].is_dir():
        wrapper = entries[0]
        for child in list(wrapper.iterdir()):
            shutil.move(str(child), str(stage_dir / child.name))
        wrapper.rmdir()
        logger.info("Flattened wrapper folder '%s' from the update archive", wrapper.name)


def find_staged_exe(stage_dir: Path, preferred_name: str | None = None) -> Path:
    """Locate the new app executable inside a staged update folder.

    Pass the current exe's filename as `preferred_name` so a package
    containing several executables still resolves to the right one.
    """
    candidates = list(stage_dir.rglob("*.exe"))
    if not candidates:
        raise InstallError("No .exe found in the downloaded update")

    if preferred_name:
        for c in candidates:
            if c.name.lower() == preferred_name.lower():
                return c

    if len(candidates) == 1:
        return candidates[0]

    raise InstallError(
        "Update package contains multiple executables and none match the "
        f"current app name ({preferred_name}) - can't tell which one to install"
    )
