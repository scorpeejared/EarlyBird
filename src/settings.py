"""
JSON-backed settings: a list of named Chrome "connections" you can pick
between per class, plus small UI preferences (like remembered window size).

Two kinds of connection:
- "uia" (default, Windows only, zero setup): attaches to a Chrome window
  you already have open normally, via Windows UI Automation. No debug
  port, no launcher script, nothing to configure in Chrome itself.
- "cdp": attaches over Chrome's remote-debugging port, which requires
  starting Chrome via a generated launcher script instead of your normal
  icon. More precise about *which* profile it's controlling when you have
  several open at once, at the cost of that one extra step.

Kept as its own tiny module (rather than another SQLite table) since it's
a handful of global values read on every join attempt, not per-meeting data.
"""
import json
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

SETTINGS_PATH = DATA_DIR / "settings.json"

_DEFAULTS = {
    "connections": [],
    "window_geometry": "",
    "updates": {
        "enabled": True,
        "channel": "stable",  # future-proofing for a "beta" channel
        "check_interval_minutes": 30,
        "skipped_version": "",  # set when the user dismisses a specific release
    },
}

ISOLATED_PROFILE_LABEL = "App's own isolated profile (default)"


def ensure_data_dir() -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_DIR


def load() -> dict:
    if not SETTINGS_PATH.exists():
        return dict(_DEFAULTS)
    try:
        data = json.loads(SETTINGS_PATH.read_text())
        merged = dict(_DEFAULTS)
        merged.update(data)
        return merged
    except (json.JSONDecodeError, OSError):
        return dict(_DEFAULTS)


def _write(full: dict) -> None:
    SETTINGS_PATH.write_text(json.dumps(full, indent=2))


def list_connections() -> list[dict]:
    return load()["connections"]


def get_connection(name: str) -> dict | None:
    for c in list_connections():
        if c["name"] == name:
            return c
    return None


def save_connections(connections: list[dict]) -> None:
    # Merge into the full settings dict rather than overwrite it - a
    # previous version of this function wrote only {"connections": ...},
    # which silently wiped out any other settings key (like window
    # geometry) every time a connection was added, edited, or removed.
    full = load()
    full["connections"] = connections
    _write(full)


def add_or_update_uia_connection(name: str, title_hint: str = "", profile_directory: str = "") -> None:
    conns = [c for c in list_connections() if c["name"] != name]
    conns.append({
        "name": name, "backend": "uia",
        "title_hint": title_hint, "profile_directory": profile_directory,
    })
    save_connections(conns)


def add_or_update_cdp_connection(name: str, profile_directory: str, port: int) -> None:
    conns = [c for c in list_connections() if c["name"] != name]
    conns.append({
        "name": name, "backend": "cdp",
        "profile_directory": profile_directory, "port": port,
    })
    save_connections(conns)


def remove_connection(name: str) -> None:
    conns = [c for c in list_connections() if c["name"] != name]
    save_connections(conns)


def connection_names() -> list[str]:
    return [ISOLATED_PROFILE_LABEL] + [c["name"] for c in list_connections()]


def get_window_geometry() -> str:
    return load().get("window_geometry", "")


def save_window_geometry(geometry: str) -> None:
    full = load()
    full["window_geometry"] = geometry
    _write(full)


def get_update_settings() -> dict:
    # Merge nested defaults too (not just top-level) so a settings.json
    # written before a new update-related key existed still picks up
    # that key's default instead of a KeyError.
    stored = load().get("updates", {})
    merged = dict(_DEFAULTS["updates"])
    merged.update(stored)
    return merged


def save_update_settings(**changes) -> None:
    full = load()
    updates = dict(_DEFAULTS["updates"])
    updates.update(full.get("updates", {}))
    updates.update(changes)
    full["updates"] = updates
    _write(full)
