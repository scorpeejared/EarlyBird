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

SETTINGS_PATH = Path(__file__).parent.parent / "data" / "settings.json"

_DEFAULTS = {
    "connections": [],
    "window_geometry": "",
}

ISOLATED_PROFILE_LABEL = "App's own isolated profile (default)"


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
