"""
Single source of truth for every location EarlyBird writes to.

In a PyInstaller build, paths derived from `__file__` land inside
`sys._MEIPASS`, a temp folder the bootloader deletes on exit - so when
frozen, user data goes to the per-user app-data directory instead. That
is also outside the install directory, so an in-place self-update that
swaps the .exe can never take a user's meetings with it. Running from
source keeps ./data and ./logs in the project root.
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
