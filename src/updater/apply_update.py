"""
The updater, living inside the app binary.

``EarlyBird.exe --apply-update ...`` is a *copy* of the newly downloaded build,
executed from %TEMP%. It waits for the running app to exit, swaps the staged
files into the install directory, starts the installed app again, and gets out
of the way.

Running the freshly downloaded copy rather than the installed one is the point:
the updater that applies an install is then the one that just shipped, so a fix
here takes effect on the very next update instead of the one after it. That lag
is what made two earlier updater bugs slow to diagnose.

Everything it needs arrives as command-line arguments. This process runs from
%TEMP%, so anything derived from ``sys.executable`` - as
``installer.get_install_dir()`` does - would point at the wrong directory.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from . import downloader, installer
from .github_release import ReleaseAsset
from .. import logging_setup, paths
from ..logging_setup import get_logger

logger = get_logger()

# Stage 2: swap the staged files in and relaunch. Run from the *new* build.
FLAG = "--apply-update"
# Stage 1: download and stage, then hand stage 2 to the build it just fetched.
DOWNLOAD_FLAG = "--download-update"

# Never replaced by an update: these are the user's, not the build's.
PRESERVE_NAMES = {"data", "logs", "settings.json"}

# How long to wait for the app to close before giving up and trying anyway.
WAIT_TIMEOUT_S = 60

# How long stage 1 waits for stage 2 to finish before assuming the new build
# is broken. Stage 2 only waits for the app to close and moves a few files.
SWAP_TIMEOUT_S = 150


class UpdateError(Exception):
    """Raised when the swap could not be completed; the old version is intact."""


def is_updater_invocation(argv: list[str]) -> bool:
    """True when these arguments mean 'run as the updater, not as the app'.

    Both stages must be listed here: dispatching on only one of them silently
    starts the normal app instead, which looks like a working update until you
    notice nothing was replaced.
    """
    return FLAG in argv or DOWNLOAD_FLAG in argv


# --------------------------------------------------------------- environment

def sanitised_environment() -> dict[str, str]:
    """A copy of this process's environment without PyInstaller's markers.

    A onefile build advertises its extraction folder through _PYI_* variables,
    and children inherit them. A relaunched onefile app that sees
    _PYI_APPLICATION_HOME_DIR, _PYI_ARCHIVE_FILE and _PYI_PARENT_PROCESS_LEVEL
    together concludes it is the already-extracted second stage and loads its
    runtime from that folder - which by then has been deleted, giving
    "Failed to load Python DLL ...\\_MEIxxxxxx\\python311.dll" naming a
    directory that no longer exists. Every process spawned from here gets a
    clean environment instead.
    """
    return {
        key: value for key, value in os.environ.items()
        if not key.startswith("_PYI_") and key != "_MEIPASS2"
    }


# ------------------------------------------------------------------ waiting

def wait_for_exit(pid: int, timeout_s: float = WAIT_TIMEOUT_S) -> bool:
    """Block until `pid` exits. True once it's gone, False on timeout."""
    if sys.platform == "win32":
        try:
            import ctypes

            SYNCHRONIZE = 0x00100000
            WAIT_TIMEOUT = 0x00000102
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            handle = kernel32.OpenProcess(SYNCHRONIZE, False, int(pid))
            if not handle:
                return True  # already gone, or not ours to wait on
            try:
                result = kernel32.WaitForSingleObject(handle, int(timeout_s * 1000))
                return result != WAIT_TIMEOUT
            finally:
                kernel32.CloseHandle(handle)
        except Exception:  # noqa: BLE001 - fall through to polling
            logger.warning("Win32 wait unavailable; polling for pid %s instead", pid)

    # POSIX only. os.kill(pid, 0) must never run on Windows: any signal other
    # than CTRL_C_EVENT/CTRL_BREAK_EVENT is delivered via TerminateProcess, so
    # the "liveness check" would kill the very app being waited for.
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            os.kill(int(pid), 0)
        except ProcessLookupError:
            return True
        except PermissionError:
            return False
        except OSError:
            return True
        time.sleep(0.25)
    return False


# -------------------------------------------------------------- the file swap

def swap(staged_dir: Path, install_dir: Path) -> list[tuple[Path, Path]]:
    """Move every staged top-level item into `install_dir`.

    Each item is swapped as a whole unit - rename the old one aside, move the
    new one in - rather than copied file by file, so one locked file out of
    hundreds can't leave a half-old, half-new install behind. If any item
    fails, everything already touched is put back and UpdateError is raised.

    Returns the backups to discard once the new version has started.
    """
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    items = [p for p in sorted(staged_dir.iterdir()) if p.name not in PRESERVE_NAMES]
    if not items:
        raise UpdateError(f"Nothing to install: {staged_dir} is empty")

    logger.info("Installing: %s", ", ".join(p.name for p in items))
    backups: list[tuple[Path, Path]] = []
    installed: list[Path] = []
    try:
        for item in items:
            destination = install_dir / item.name
            if destination.exists():
                backup = install_dir / f"{item.name}.bak_{stamp}"
                destination.rename(backup)
                backups.append((destination, backup))
                logger.info("Backed up '%s' -> '%s'", item.name, backup.name)
            shutil.move(str(item), str(destination))
            installed.append(destination)
            logger.info("Installed new '%s'", item.name)
    except OSError as e:
        logger.error("Update failed partway (%s); rolling back", e)
        _rollback(installed, backups)
        raise UpdateError(str(e)) from e
    return backups


def _rollback(installed: list[Path], backups: list[tuple[Path, Path]]) -> None:
    """Undo a partial swap so the previous version is left working."""
    for path in installed:
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        else:
            try:
                path.unlink()
            except OSError:
                pass
    for original, backup in backups:
        try:
            backup.rename(original)
        except OSError as e:  # noqa: PERF203 - each restore is independent
            logger.error("Could not restore '%s': %s", original.name, e)
    logger.info("Rollback complete - the previous version should still be intact")


def discard_backups(backups: list[tuple[Path, Path]]) -> None:
    """Remove the renamed-aside originals. Best effort: a leftover .bak only
    wastes disk until the next update."""
    for _, backup in backups:
        try:
            if backup.is_dir():
                shutil.rmtree(backup)
            else:
                backup.unlink()
            logger.info("Removed backup '%s'", backup.name)
        except OSError as e:
            logger.warning("Could not remove backup '%s': %s", backup.name, e)


def relaunch(exe: Path) -> None:
    creationflags = 0x00000200 if sys.platform == "win32" else 0  # NEW_PROCESS_GROUP
    subprocess.Popen(
        [str(exe)],
        cwd=str(exe.parent),
        env=sanitised_environment(),
        creationflags=creationflags,
        close_fds=True,
    )
    logger.info("Relaunched %s", exe)


def cleanup_stale_updates() -> None:
    """Clear what an update leaves in %TEMP%, called from normal startup.

    This is the only safe place to do it: the runner that performed the swap
    has finished by the time the new app is up, and the downloaded asset is a
    ~96 MB file that used to survive every update. Anything still locked is
    simply left for the next start.
    """
    root = downloader.staging_dir()
    for name in ("runner", "staged"):
        shutil.rmtree(root / name, ignore_errors=True)
    try:
        for leftover in root.iterdir():
            if leftover.is_file() and leftover.suffix.lower() != ".log":
                try:
                    leftover.unlink()
                except OSError:
                    pass
    except OSError:
        pass


# ------------------------------------------------------------ the updater run

def parse_args(argv: list[str]) -> argparse.Namespace:
    """Arguments for either stage; which one is decided by the flag present."""
    parser = argparse.ArgumentParser(prog="EarlyBird", add_help=False)
    parser.add_argument(FLAG, action="store_true", dest="apply_update")
    parser.add_argument(DOWNLOAD_FLAG, action="store_true", dest="download_update")
    parser.add_argument("--wait-pid", type=int, required=True)
    parser.add_argument("--install-dir", type=Path, required=True)
    parser.add_argument("--relaunch-name", required=True)
    # stage 2 only
    parser.add_argument("--staged-dir", type=Path)
    # stage 1 only
    parser.add_argument("--url")
    parser.add_argument("--asset-name")
    parser.add_argument("--asset-size", type=int, default=0)
    parser.add_argument("--version", default="")
    args = parser.parse_args(argv)
    if args.apply_update and args.staged_dir is None:
        parser.error("--apply-update requires --staged-dir")
    if args.download_update and not (args.url and args.asset_name):
        parser.error("--download-update requires --url and --asset-name")
    return args


def run(args: argparse.Namespace, on_status=None) -> None:
    """The whole update, headless. Raises UpdateError if it couldn't finish."""

    def status(message: str) -> None:
        logger.info(message)
        if on_status:
            on_status(message)

    status("Waiting for EarlyBird to close...")
    if not wait_for_exit(args.wait_pid):
        # Proceed anyway: a rename of a still-running exe is allowed on
        # Windows, and if it genuinely can't be moved the swap rolls back.
        logger.warning("pid %s did not exit within %ss; continuing",
                       args.wait_pid, WAIT_TIMEOUT_S)
    # File locks can briefly outlive the process itself.
    time.sleep(1.0)

    status("Replacing files...")
    backups = swap(args.staged_dir, args.install_dir)

    status("Starting EarlyBird...")
    relaunch(args.install_dir / args.relaunch_name)

    discard_backups(backups)
    shutil.rmtree(args.staged_dir, ignore_errors=True)
    status("Update complete")


def run_download(args: argparse.Namespace, on_status=None, on_progress=None) -> None:
    """Stage 1: fetch the new build, then let *it* perform the swap.

    This runs from a copy of the *installed* binary - the new one doesn't
    exist yet - but it hands the actual file swap to what it just downloaded.
    That keeps the install logic that runs equal to the newest shipped one,
    and doubles as a smoke test: a build that can't start never gets the
    chance to replace a working install. If stage 2 doesn't report success,
    nothing has been replaced and the current version is reopened instead.
    """

    def status(message: str) -> None:
        logger.info(message)
        if on_status:
            on_status(message)

    status("Downloading update...")
    asset = ReleaseAsset(name=args.asset_name, download_url=args.url,
                         size_bytes=args.asset_size or 0)
    downloaded = downloader.download_asset(asset, on_progress=on_progress)

    status("Preparing update...")
    stage_dir = installer.stage_update(downloaded)
    staged_exe = installer.find_staged_exe(stage_dir, preferred_name=args.relaunch_name)

    # A onedir build's application code lives in _internal/, not in the thin
    # exe stub. Swapping only the exe would leave the old _internal/ in place
    # and the app would silently keep running the old version.
    if (args.install_dir / "_internal").is_dir() and not (stage_dir / "_internal").is_dir():
        raise UpdateError(
            f"This is a onedir install, but the release asset '{args.asset_name}' "
            "contained only a bare .exe with no _internal/ folder. The asset needs "
            "to be a .zip of the whole dist/EarlyBird/ folder."
        )

    # Stage 2 runs from its own folder: it moves the staged files into place,
    # and a running executable can't move itself.
    swapper_dir = downloader.staging_dir() / "swapper"
    shutil.rmtree(swapper_dir, ignore_errors=True)
    swapper_dir.mkdir(parents=True, exist_ok=True)
    swapper_exe = swapper_dir / staged_exe.name
    shutil.copy2(staged_exe, swapper_exe)

    command = [
        str(swapper_exe), FLAG,
        "--wait-pid", str(args.wait_pid),
        "--install-dir", str(args.install_dir),
        "--staged-dir", str(stage_dir),
        "--relaunch-name", args.relaunch_name,
    ]
    status("Installing update...")
    logger.info("Handing off to the new build: %s", " ".join(command))
    creationflags = 0x00000200 if sys.platform == "win32" else 0
    swapper = subprocess.Popen(
        command, cwd=str(swapper_dir), env=sanitised_environment(),
        creationflags=creationflags, close_fds=True,
    )

    try:
        exit_code = swapper.wait(timeout=SWAP_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        swapper.kill()
        raise UpdateError(
            "The new version did not finish installing in time. Nothing has "
            "been replaced, so your current version is untouched."
        ) from None

    if exit_code != 0:
        raise UpdateError(
            f"The new version could not install itself (exit code {exit_code}). "
            "Your current version is untouched."
        )
    status("Update complete")


def recover(args: argparse.Namespace) -> None:
    """Stage 2 never succeeded, so nothing was replaced - reopen what's there."""
    try:
        relaunch(args.install_dir / args.relaunch_name)
    except OSError as e:  # noqa: BLE001 - already reporting a failure
        logger.error("Could not reopen the current version: %s", e)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    logging_setup.configure()
    stage = "download" if args.download_update else "apply"
    logger.info("=== updater started (%s stage, pid %s, waiting on %s) ===",
                stage, os.getpid(), args.wait_pid)

    # Imported here so the module stays importable (and testable) without Qt.
    from .updater_window import run_with_window

    log_path = paths.LOG_DIR / logging_setup.LOG_FILENAME
    if args.download_update:
        return run_with_window(args, run_download, log_path,
                               title_version=args.version,
                               show_progress=True, on_failure=recover)
    return run_with_window(args, run, log_path)
