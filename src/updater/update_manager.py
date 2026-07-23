"""
Public facade for the update subsystem.

Mirrors SchedulerService's threading shape on purpose (start/stop,
daemon thread, a cancellable `_stop_event.wait(interval)` loop, an
`on_status_change` callback) so anyone already familiar with
scheduler.py recognizes this immediately, and so both background
services behave consistently under app shutdown.

Usage from main.py:

    self.update_manager = UpdateManager(
        repo_owner="scorpeejared",
        repo_name="EarlyBird",
        on_update_available=self._on_update_available,   # UI callback
        on_status_change=self._on_scheduler_status,       # reuse existing status line
    )
    self.update_manager.start()

`on_update_available` is called from the background thread - like
SchedulerService.on_status_change, callers must hop back to the Tk
thread themselves (`self.after(0, ...)`) before touching any widgets.
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Callable

from . import downloader, github_release, installer, update_checker, updater_launcher
from .github_release import ReleaseInfo
from .version import get_installed_version
from .. import settings

logger = logging.getLogger("meet_automation")

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

    def check_for_updates(self) -> update_checker.UpdateCheckResult:
        """Check GitHub Releases now, outside the normal poll interval.

        Safe to call directly from a "Check for updates" menu item -
        it does not require the background thread to be running.
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
            if result.release.tag == skipped:
                logger.info("Skipping already-dismissed version %s", result.release.tag)
                return result
            if result.release.tag != self._already_notified_tag:
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

        Returns True if a relaunch was actually staged - i.e. the
        caller should now proceed to close the app, since something
        will bring it back. Returns False if this ran against a dev
        (`python main.py`) checkout: the download/stage still happened
        and was verified, but there's no installed .exe to swap, so
        nothing will relaunch the app - the caller must NOT quit in
        that case, or the app just closes and never comes back.

        Does NOT close the app itself even when it returns True - by
        design, so the caller (the UI layer) controls exactly when/how
        the app shuts down (saving window geometry, stopping the
        scheduler, etc.) using its own existing shutdown path, the
        same way `App._quit()` already does for a normal close.
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

        if not installer.is_frozen():
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

        # A onedir build's actual application code lives in _internal/,
        # not in the thin exe stub - if the release asset was just the
        # bare .exe (not a .zip of the whole onedir folder), swapping
        # only the exe leaves the OLD _internal/ in place, so the app
        # silently keeps running the old version with no error anywhere.
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

        # The staged folder should relaunch via the *new* exe, at the
        # same filename/location the current one lives at.
        relaunch_target = install_dir / current_exe.name if staged_exe.name == current_exe.name else staged_exe

        log_path = updater_launcher.launch(
            stage_dir=stage_dir,
            install_dir=install_dir,
            relaunch_exe=relaunch_target,
            updates_root=downloader.staging_dir(),
        )
        self.last_update_log_path = log_path
        self._report("Update staged - restarting...")
        return True

    def _report(self, message: str) -> None:
        logger.info(message)
        if self.on_status_change:
            self.on_status_change(message)
