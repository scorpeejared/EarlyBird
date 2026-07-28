"""
Single source of truth for every location EarlyBird writes to.

Why this module exists: in a PyInstaller --onefile build, `__file__` for
a bundled module points inside `sys._MEIPASS` - a temporary folder the
bootloader deletes as soon as the app exits. Any path built from
`Path(__file__).parent...` therefore *looks* fine at runtime (the write
succeeds, nothing errors) but is gone by the next launch. That's exactly
how meetings.db and settings.json were silently disappearing between
runs of the packaged app.

So, when frozen, everything the user owns lives under the per-user
app-data directory instead. That location is also deliberately outside
the install directory, so an in-place self-update that swaps the .exe
can never take a user's meetings with it.

When running from source (`python main.py`) the layout is unchanged -
the project root - so a dev checkout keeps using ./data and ./logs.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "EarlyBird"


def is_frozen() -> bool:
    """True when running as a PyInstaller build, False for `python main.py`."""
    return bool(getattr(sys, "frozen", False))


def _user_data_root() -> Path:
    """The OS's conventional per-user application-data directory."""
    if sys.platform == "win32":
        local_app_data = os.environ.get("LOCALAPPDATA")
        return Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support"
    xdg = os.environ.get("XDG_DATA_HOME")
    return Path(xdg) if xdg else Path.home() / ".local" / "share"


def app_dir() -> Path:
    """Root folder holding this app's data, logs and generated files."""
    if is_frozen():
        return _user_data_root() / APP_NAME
    return Path(__file__).resolve().parent.parent


APP_DIR = app_dir()

DATA_DIR = APP_DIR / "data"
LOG_DIR = APP_DIR / "logs"
LAUNCHER_DIR = APP_DIR / "launchers"
PROFILE_DIR = APP_DIR / "chrome_profile"

DB_PATH = DATA_DIR / "meetings.db"
SETTINGS_PATH = DATA_DIR / "settings.json"


def ensure_dirs() -> Path:
    """Create the folders the app writes to. Safe to call repeatedly."""
    for directory in (DATA_DIR, LOG_DIR):
        directory.mkdir(parents=True, exist_ok=True)
    return APP_DIR
