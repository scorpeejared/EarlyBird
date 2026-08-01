"""
JSON-backed settings: a list of named browser "connections" you can pick
between per class, plus small UI preferences (like remembered window size).

Two kinds of connection:
- "uia" (default, Windows only, zero setup): drives a browser window via
  Windows UI Automation. No debug port, no launcher script, nothing to
  configure in the browser itself.
- "cdp": attaches over the browser's remote-debugging port, which requires
  starting it via a generated launcher script instead of your normal
  icon. More precise about *which* profile it's controlling when you have
  several open at once, at the cost of that one extra step.

Each connection also records which browser it drives ("chrome", "edge",
"brave", "opera", "opera_gx"). Connections saved before that field existed
read back as Chrome.
"""
import json
from pathlib import Path

from . import browsers, paths

DATA_DIR = paths.DATA_DIR
SETTINGS_PATH = paths.SETTINGS_PATH

_DEFAULTS = {
    "connections": [],
    "theme_mode": "auto",  # "light" | "dark" | "auto" (follow system)
    "updates": {
        "enabled": True,
        "channel": "stable",  # only "stable" is wired up today
        "check_interval_minutes": 30,
        "skipped_version": "",  # set when the user dismisses a specific release
    },
}

ISOLATED_PROFILE_LABEL = "App's own isolated profile (default)"


def ensure_data_dir() -> Path:
    """Create the data folder and seed settings.json if it isn't there,
    so the file always exists to inspect or hand-edit."""
    paths.ensure_dirs()
    if not SETTINGS_PATH.exists():
        _write(dict(_DEFAULTS))
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
    # mkdir here too, in case the folder was removed while the app ran.
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(full, indent=2))


def _with_browser(conn: dict) -> dict:
    """A copy of the connection with a guaranteed-valid browser id.

    Applied on read so a settings.json written by an older build (no browser
    key at all) behaves exactly as it did: as Chrome.
    """
    normalized = dict(conn)
    normalized["browser"] = browsers.normalize(conn.get("browser"))
    return normalized


def list_connections() -> list[dict]:
    return [_with_browser(c) for c in load()["connections"]]


def connection_browser(conn: dict | None) -> str:
    """Browser id for a connection dict, defaulting to Chrome (incl. for None)."""
    return browsers.normalize(conn.get("browser") if conn else None)


def get_connection(name: str) -> dict | None:
    for c in list_connections():
        if c["name"] == name:
            return c
    return None


def save_connections(connections: list[dict]) -> None:
    # Merge into the full settings dict rather than overwrite it, or
    # every connection edit wipes out the other settings keys.
    full = load()
    full["connections"] = [_with_browser(c) for c in connections]
    _write(full)


def add_or_update_uia_connection(
    name: str,
    title_hint: str = "",
    profile_directory: str = "",
    browser: str = browsers.DEFAULT,
) -> None:
    conns = [c for c in list_connections() if c["name"] != name]
    conns.append({
        "name": name, "backend": "uia", "browser": browsers.normalize(browser),
        "title_hint": title_hint, "profile_directory": profile_directory,
    })
    save_connections(conns)


def add_or_update_cdp_connection(
    name: str,
    profile_directory: str,
    port: int,
    browser: str = browsers.DEFAULT,
) -> None:
    conns = [c for c in list_connections() if c["name"] != name]
    conns.append({
        "name": name, "backend": "cdp", "browser": browsers.normalize(browser),
        "profile_directory": profile_directory, "port": port,
    })
    save_connections(conns)


def remove_connection(name: str) -> None:
    conns = [c for c in list_connections() if c["name"] != name]
    save_connections(conns)


def connection_names() -> list[str]:
    return [ISOLATED_PROFILE_LABEL] + [c["name"] for c in list_connections()]


def get_theme_mode() -> str:
    mode = load().get("theme_mode", "auto")
    return mode if mode in ("light", "dark", "auto") else "auto"


def save_theme_mode(mode: str) -> None:
    full = load()
    full["theme_mode"] = mode
    _write(full)


def get_update_settings() -> dict:
    # Merge the nested defaults too, so a settings.json written before a
    # new update key existed picks up that key's default instead of a KeyError.
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
