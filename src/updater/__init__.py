"""
Auto-update subsystem for EarlyBird.

Checking GitHub Releases, downloading assets, staging the install, and
relaunching all live here behind one facade, ``UpdateManager``. Nothing
outside this package imports github_release, downloader, or installer
directly.

The exception is ``apply_update``: main.py imports it to dispatch the
``--apply-update`` mode, which is this same binary acting as the updater
for a new build.
"""
from .update_manager import UpdateManager
from .github_release import ReleaseInfo
from .version import __version__

__all__ = ["UpdateManager", "ReleaseInfo", "__version__"]
