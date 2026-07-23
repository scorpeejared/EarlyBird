"""
Auto-update subsystem for EarlyBird.

Everything update-related (checking GitHub Releases, downloading assets,
staging the install, relaunching the app) lives in this package and is
reached through a single facade: `update_manager.UpdateManager`.

The rest of the app should only ever need:

    from src.updater import UpdateManager, ReleaseInfo

    self.update_manager = UpdateManager(on_update_available=..., on_status_change=...)
    self.update_manager.start()

No other module in the app should import github_release, downloader,
installer, or updater_launcher directly - that keeps the update flow
swappable (e.g. adding a beta channel, or a signature check) without
touching scheduler.py, storage.py, or main.py's UI code.
"""
from .update_manager import UpdateManager
from .github_release import ReleaseInfo
from .version import __version__

__all__ = ["UpdateManager", "ReleaseInfo", "__version__"]
