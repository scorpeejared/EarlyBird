"""
Prepares a downloaded release asset to actually replace the running
app's files.

The tricky constraint this whole module exists to handle: on Windows
you cannot overwrite (or delete) the .exe of a process that's still
running. So "installing" never touches the live install directory
directly - it only ever unpacks/stages the new build into a scratch
folder next to it. The actual file swap happens in updater_launcher.py,
by a *separate* process, after this process has exited.
"""
from __future__ import annotations

import logging
import shutil
import sys
import zipfile
from pathlib import Path

logger = logging.getLogger("meet_automation")


def is_frozen() -> bool:
    """True when running as a PyInstaller build, False for `python main.py`."""
    return bool(getattr(sys, "frozen", False))


def get_install_dir() -> Path:
    """Directory containing the running app's files.

    - Frozen (PyInstaller onefile or onedir): the folder holding the
      .exe, i.e. `Path(sys.executable).parent`.
    - Running from source: the project root (parent of `src/`) - self-
      update isn't meaningful here, but keeping this well-defined means
      update_manager can still run in "check only" mode during
      development without special-casing every call site.
    """
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent.parent


def get_current_exe_path() -> Path:
    if not is_frozen():
        raise RuntimeError("get_current_exe_path() only applies to a packaged (frozen) build")
    return Path(sys.executable).resolve()


class InstallError(Exception):
    pass


def stage_update(downloaded_path: Path) -> Path:
    """Unpack/prepare a downloaded asset into a staging folder that
    mirrors the final install layout, and return that folder's path.

    Handles two asset shapes:
    - A .zip containing the built app (onedir-style output, or a
      zipped onefile exe) - extracted in place.
    - A raw executable (onefile build uploaded directly as a release
      asset) - copied as-is; the staged folder then contains just the
      one new .exe.
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
    """If the zip's only top-level entry is itself a folder (e.g. it
    was zipped by right-clicking `dist/EarlyBird/` rather than zipping
    its *contents*), move that folder's contents up one level.

    Without this, the updater script's top-level swap (exe + _internal)
    would look for those names directly under `stage_dir` and find
    nothing there - it'd see one folder named e.g. "EarlyBird" instead.
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

    `preferred_name` should normally be the current exe's own filename
    (e.g. "EarlyBird.exe") so a onedir zip that contains several DLLs
    alongside the exe still resolves to the right file.
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
