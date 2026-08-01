"""
Public facade for the update subsystem.

Mirrors SchedulerService's threading shape (start/stop, daemon thread, a
cancellable `_stop_event.wait(interval)` loop, an `on_status_change`
callback) so both background services behave alike under app shutdown.

Both callbacks fire on the background thread; callers must hop back to
the GUI thread themselves before touching widgets - MainWindow does this
with the queued signals on ``_EventBridge``.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from typing import Callable

from . import apply_update, downloader, github_release, installer, update_checker
from .github_release import ReleaseInfo
from .version import get_installed_version
from .. import logging_setup, paths, settings
from ..logging_setup import get_logger

logger = get_logger()

DEFAULT_CHECK_INTERVAL_MINUTES = 30
ASSET_NAME_HINT = "EarlyBird"  # substring match against release asset filenames


class UpdateManager:
    def __init__(
        self,
        repo_owner: str,
        repo_name: str,
        asset_name_hint: str = ASSET_NAME_HINT,
        on_update_available: Callable[[ReleaseInfo], None] | None = None,
        on_status_change: Callable[[str], None] | None = None,
    ):
        self.repo_owner = repo_owner
        self.repo_name = repo_name
        self.asset_name_hint = asset_name_hint
        self.on_update_available = on_update_available
        self.on_status_change = on_status_change

        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._already_notified_tag: str | None = None
        self.latest_known_release: ReleaseInfo | None = None
        self.last_update_log_path: Path | None = None

    # ---------- lifecycle ----------

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        if not settings.get_update_settings()["enabled"]:
            logger.info("Update checks disabled in settings; not starting update manager")
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        logger.info("Update manager started")

    def stop(self) -> None:
        self._stop_event.set()

    def _run(self) -> None:
        # Check once immediately on startup, then keep polling at the
        # configured interval for as long as the app runs.
        self.check_for_updates()
        while not self._stop_event.is_set():
            interval_seconds = settings.get_update_settings()["check_interval_minutes"] * 60
            if self._stop_event.wait(interval_seconds):
                break
            self.check_for_updates()

    # ---------- checking ----------

    def check_for_updates(self, force: bool = False) -> update_checker.UpdateCheckResult:
        """Check GitHub Releases now; does not need the background thread.

        `force=True` (the Settings page button) bypasses the dismissed-
        version skip and the already-notified de-dupe, which exist only
        to stop the silent background poll from nagging. A manual click
        should always surface a real answer.
        """
        try:
            release = github_release.get_latest_release(self.repo_owner, self.repo_name)
        except github_release.GitHubReleaseError as e:
            logger.warning("Update check failed: %s", e)
            self._report(f"Update check failed: {e}")
            return update_checker.UpdateCheckResult(
                update_available=False, current_version=get_installed_version(), release=None
            )

        result = update_checker.check(release)
        self.latest_known_release = result.release

        if result.update_available and result.release:
            skipped = settings.get_update_settings()["skipped_version"]
            if not force and result.release.tag == skipped:
                logger.info("Skipping already-dismissed version %s", result.release.tag)
                return result
            if force or result.release.tag != self._already_notified_tag:
                self._already_notified_tag = result.release.tag
                self._report(f"Update available: {result.release.tag}")
                if self.on_update_available:
                    self.on_update_available(result.release)
        else:
            self._report("Up to date")

        return result

    def dismiss(self, release: ReleaseInfo) -> None:
        """User chose 'Later' - don't nag again for this specific
        version, but do still notify if a *newer* one comes out."""
        settings.save_update_settings(skipped_version=release.tag)

    # ---------- installing ----------

    def download_and_install(
        self,
        release: ReleaseInfo,
        on_progress: Callable[[int, int], None] | None = None,
    ) -> bool:
        """Download the release asset, stage it, and (on a packaged
        build) launch the detached updater process.

        Returns True when a relaunch is staged, meaning the caller should
        now close the app - something will bring it back. Returns False
        for a dev checkout, where the download is verified but there's no
        installed .exe to swap: quitting then would close the app for
        good. Never closes the app itself, so the UI layer keeps control
        of its own shutdown path.
        """
        asset = release.pick_asset(self.asset_name_hint)
        if asset is None:
            raise RuntimeError(
                f"No release asset matched '{self.asset_name_hint}' for {release.tag}"
            )

        self._report(f"Downloading {release.tag}...")
        downloaded_path = downloader.download_asset(asset, on_progress=on_progress)

        self._report("Preparing update...")
        stage_dir = installer.stage_update(downloaded_path)

        if not paths.is_frozen():
            logger.warning(
                "Running from source (not a packaged build) - staged the update at %s "
                "but skipping the file swap, since there's no installed .exe to replace.",
                stage_dir,
            )
            self._report(f"Update downloaded to {stage_dir} (dev mode: not auto-installed)")
            return False

        current_exe = installer.get_current_exe_path()
        install_dir = installer.get_install_dir()
        staged_exe = installer.find_staged_exe(stage_dir, preferred_name=current_exe.name)

        # A onedir build's application code lives in _internal/, not in
        # the thin exe stub. Swapping only the exe leaves the old
        # _internal/ in place and the app silently runs the old version.
        installed_has_internal = (install_dir / "_internal").is_dir()
        staged_has_internal = (stage_dir / "_internal").is_dir()
        if installed_has_internal and not staged_has_internal:
            raise RuntimeError(
                "This is a onedir build (it has an _internal/ folder), but the "
                f"downloaded release asset '{asset.name}' only contained a bare "
                ".exe with no _internal/ folder. The release asset needs to be a "
                ".zip of the whole dist/EarlyBird/ folder (exe + _internal/), not "
                "just the .exe by itself - otherwise the app's actual code never "
                "gets updated even though the launcher exe does."
            )

        # Relaunch from the install directory, always. The updater *moves* the
        # staged files into place and then deletes the staging folder, so a
        # path inside it is gone by the time the relaunch runs - which is what
        # happened when the installed exe had been renamed (a browser's
        # "EarlyBird (1).exe") and the names didn't match.
        relaunch_target = install_dir / staged_exe.name

        # Run the *downloaded* build as the updater, from its own temp folder.
        # It is the new version, so the updater logic that applies an install
        # is always the one that just shipped - a fix here reaches users on the
        # next update rather than the one after it. Copying it out of the
        # staging folder also leaves that folder free to be moved wholesale.
        runner_dir = downloader.staging_dir() / "runner"
        shutil.rmtree(runner_dir, ignore_errors=True)
        runner_dir.mkdir(parents=True, exist_ok=True)
        runner_exe = runner_dir / staged_exe.name
        shutil.copy2(staged_exe, runner_exe)

        command = [
            str(runner_exe),
            apply_update.FLAG,
            "--wait-pid", str(os.getpid()),
            "--install-dir", str(install_dir),
            "--staged-dir", str(stage_dir),
            "--relaunch-name", relaunch_target.name,
        ]
        # CREATE_NEW_PROCESS_GROUP unties the updater from this process's
        # lifetime and signals; it has to outlive us to do its job.
        creationflags = 0x00000200 if sys.platform == "win32" else 0
        subprocess.Popen(
            command,
            cwd=str(runner_dir),
            env=apply_update.sanitised_environment(),
            creationflags=creationflags,
            close_fds=True,
        )
        logger.info("Launched updater: %s", " ".join(command))

        self.last_update_log_path = paths.LOG_DIR / logging_setup.LOG_FILENAME
        self._report("Update staged - restarting...")
        return True

    def _report(self, message: str) -> None:
        logger.info(message)
        if self.on_status_change:
            self.on_status_change(message)
