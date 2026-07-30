"""
Auto-update subsystem for EarlyBird.

Checking GitHub Releases, downloading assets, staging the install, and
relaunching all live here behind one facade, ``UpdateManager``. Nothing
outside this package imports github_release, downloader, installer, or
updater_launcher directly.
"""
from .update_manager import UpdateManager
from .github_release import ReleaseInfo
from .version import __version__

__all__ = ["UpdateManager", "ReleaseInfo", "__version__"]
