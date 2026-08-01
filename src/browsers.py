"""
The set of browsers a connection can drive, and the helpers for reading
that value back safely.

Every browser-specific detail (Playwright channel, executable path, UIA
window class) hangs off these identifiers, so this module is deliberately
dependency-free - automation, launchers and the UI can all import it.

Chrome is the default everywhere: a record that predates this field, or
one carrying a value this build doesn't know, normalizes to Chrome so
existing setups keep the exact behaviour they had before.
"""
from __future__ import annotations

import os
import sys

CHROME = "chrome"
EDGE = "edge"
BRAVE = "brave"
OPERA = "opera"
OPERA_GX = "opera_gx"

DEFAULT = CHROME

ALL = (CHROME, EDGE, BRAVE, OPERA, OPERA_GX)

# What the UI actually offers today. Extended one browser at a time as each
# is implemented and tested, so the dropdown never advertises a half-built path.
SUPPORTED = (CHROME, EDGE, BRAVE, OPERA, OPERA_GX)

DISPLAY_NAMES = {
    CHROME: "Google Chrome",
    EDGE: "Microsoft Edge",
    BRAVE: "Brave",
    OPERA: "Opera",
    OPERA_GX: "Opera GX",
}


# Short forms for running text ("Make sure Chrome is open before then.").
SHORT_NAMES = {
    CHROME: "Chrome",
    EDGE: "Edge",
    BRAVE: "Brave",
    OPERA: "Opera",
    OPERA_GX: "Opera GX",
}


def normalize(value: str | None) -> str:
    """Map any stored/user value onto a known browser id, defaulting to Chrome."""
    if not value:
        return DEFAULT
    candidate = str(value).strip().lower().replace("-", "_").replace(" ", "_")
    return candidate if candidate in ALL else DEFAULT


def display_name(value: str | None) -> str:
    return DISPLAY_NAMES[normalize(value)]


def short_name(value: str | None) -> str:
    return SHORT_NAMES[normalize(value)]


def is_chrome(value: str | None) -> bool:
    """True for the default path - the one that must stay byte-for-byte unchanged."""
    return normalize(value) == CHROME


# ---------------------------------------------------------------- Playwright

# Playwright ships first-class support for these via channel=; anything not
# listed here has to be launched by executable_path instead.
PLAYWRIGHT_CHANNELS = {
    CHROME: "chrome",
    EDGE: "msedge",
}


def playwright_channel(value: str | None) -> str | None:
    """The Playwright `channel` for this browser, or None if it needs a path."""
    return PLAYWRIGHT_CHANNELS.get(normalize(value))


# --------------------------------------------------------- Windows UIA lookup

# Chromium browsers name their top-level window class Chrome_WidgetWin_1 - and
# so does every Electron app (VS Code, Discord), which is why the class is never
# used on its own; process_images() below is what actually identifies a browser.
WINDOW_CLASSES = {
    CHROME: "Chrome_WidgetWin_1",
    EDGE: "Chrome_WidgetWin_1",
    BRAVE: "Chrome_WidgetWin_1",
    OPERA: "Chrome_WidgetWin_1",
    OPERA_GX: "Chrome_WidgetWin_1",
}

# Which of those were confirmed by actually running the browser and reading the
# class off a live window, rather than inferred from "it's a Chromium fork".
# Enumeration falls back to a process-only sweep for the unconfirmed ones, so a
# wrong guess here costs a little speed instead of breaking the browser.
VERIFIED_WINDOW_CLASSES = (CHROME, EDGE, BRAVE, OPERA_GX)


def window_class(value: str | None) -> str:
    return WINDOW_CLASSES.get(normalize(value), "Chrome_WidgetWin_1")


def window_class_is_verified(value: str | None) -> bool:
    return normalize(value) in VERIFIED_WINDOW_CLASSES


# Executable names a window's owning process must have to count as this browser.
PROCESS_IMAGES = {
    CHROME: ("chrome.exe",),
    EDGE: ("msedge.exe",),
    BRAVE: ("brave.exe",),
    # Opera and Opera GX ship the same executable name, so the image alone
    # can't tell them apart - the path markers below finish the job.
    OPERA: ("opera.exe",),
    OPERA_GX: ("opera.exe",),
}

# Lowercased fragments the executable's full path must contain (markers) or
# must not contain (excludes). This is what separates the two Operas.
PATH_MARKERS = {
    OPERA_GX: ("opera gx",),
}
PATH_EXCLUDES = {
    OPERA: ("opera gx",),
}


def process_images(value: str | None) -> tuple[str, ...]:
    return PROCESS_IMAGES.get(normalize(value), ())


def matches_executable(value: str | None, executable_path: str | None) -> bool:
    """Whether a running process's exe path belongs to this browser."""
    browser = normalize(value)
    images = process_images(browser)
    if not images or not executable_path:
        return False
    path = executable_path.lower().replace("/", "\\")
    if os.path.basename(path) not in images:
        return False
    markers = PATH_MARKERS.get(browser, ())
    if markers and not any(m in path for m in markers):
        return False
    return not any(x in path for x in PATH_EXCLUDES.get(browser, ()))


# ------------------------------------------------------------ Profile layout

# Chromium keeps many named profiles inside one "User Data" folder and picks
# between them with --profile-directory. Opera instead gives each install a
# single profile folder and is pointed at it with --user-data-dir - there are
# no numbered profiles to choose from, so the UI asks for a folder instead of
# a profile name.
PROFILE_MODE_CHROMIUM = "chromium"
PROFILE_MODE_SINGLE_DIR = "single_dir"

PROFILE_MODES = {
    CHROME: PROFILE_MODE_CHROMIUM,
    EDGE: PROFILE_MODE_CHROMIUM,
    BRAVE: PROFILE_MODE_CHROMIUM,
    OPERA: PROFILE_MODE_SINGLE_DIR,
    OPERA_GX: PROFILE_MODE_SINGLE_DIR,
}


# Browsers that open a startup page of their own (Opera's GX Corner / speed
# dial). Closing those pages takes minutes and then tears down the whole
# context, taking the meeting tab with it - so they are left alone.
KEEPS_STARTUP_PAGES = (OPERA, OPERA_GX)


def keeps_startup_pages(value: str | None) -> bool:
    return normalize(value) in KEEPS_STARTUP_PAGES


def profile_mode(value: str | None) -> str:
    return PROFILE_MODES.get(normalize(value), PROFILE_MODE_CHROMIUM)


def uses_single_profile_dir(value: str | None) -> bool:
    return profile_mode(value) == PROFILE_MODE_SINGLE_DIR


# Where each single-profile-dir browser keeps that folder by default; used as
# the placeholder in the UI so there's something concrete to recognise.
_DEFAULT_PROFILE_DIRS = {
    OPERA: {
        "win32": r"%APPDATA%\Opera Software\Opera Stable",
        "darwin": "~/Library/Application Support/com.operasoftware.Opera",
        "linux": "~/.config/opera",
    },
    OPERA_GX: {
        "win32": r"%APPDATA%\Opera Software\Opera GX Stable",
        "darwin": "~/Library/Application Support/com.operasoftware.OperaGX",
        "linux": "",
    },
}


def default_profile_dir(value: str | None) -> str:
    """Conventional profile folder for this browser on this OS ("" if n/a)."""
    per_os = _DEFAULT_PROFILE_DIRS.get(normalize(value))
    if not per_os:
        return ""
    key = sys.platform if sys.platform in per_os else "linux"
    return os.path.expandvars(per_os.get(key, ""))


def split_profile_path(path: str) -> tuple[str, str]:
    """Split an Opera profile path into (user_data_dir, profile_directory).

    Opera is Chromium underneath: a user-data-dir holding profile subfolders.
    What opera://about reports as "Profile path" is the *profile* half -
    e.g. ...\\Opera GX Stable\\_side_profiles\\<id>\\Default - and passing that
    whole thing as --user-data-dir makes Opera create a fresh empty profile
    nested inside the real one, which is not the profile the user meant.

    The folders identify themselves: a profile holds Preferences, a
    user-data-dir holds Local State. Checked in that order, because a folder
    left over from the mistake above can end up with both.
    """
    cleaned = path.strip().strip('"').rstrip("\\/")
    if not cleaned:
        return "", ""
    if os.path.isfile(os.path.join(cleaned, "Preferences")):
        return os.path.dirname(cleaned), os.path.basename(cleaned)
    if os.path.isfile(os.path.join(cleaned, "Local State")):
        # A user-data-dir: use its standard profile if that's there.
        if os.path.isdir(os.path.join(cleaned, "Default")):
            return cleaned, "Default"
        return cleaned, ""
    # Not on disk (a path typed from memory, or another machine): treat it as
    # the user-data-dir, which is what it was before this split existed.
    return cleaned, ""


def profile_launch_args(value: str | None, profile: str) -> list[str]:
    """Command-line flags that select `profile` for this browser."""
    if not profile:
        return []
    if uses_single_profile_dir(value):
        user_data_dir, profile_directory = split_profile_path(profile)
        args = [f"--user-data-dir={user_data_dir}"]
        if profile_directory:
            args.append(f"--profile-directory={profile_directory}")
        return args
    return [f"--profile-directory={profile}"]


# The page whose "Profile path" field tells a user what to paste.
VERSION_PAGES = {
    CHROME: "chrome://version",
    EDGE: "edge://version",
    BRAVE: "brave://version",
    OPERA: "opera://about",
    OPERA_GX: "opera://about",
}


def version_page(value: str | None) -> str:
    return VERSION_PAGES.get(normalize(value), "chrome://version")


# ------------------------------------------------------------- Install lookup

_WINDOWS_EXES = {
    CHROME: [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe",
    ],
    EDGE: [
        # Edge Stable installs 32-bit-path-side even on 64-bit Windows.
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe",
    ],
    BRAVE: [
        r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
        r"C:\Program Files (x86)\BraveSoftware\Brave-Browser\Application\brave.exe",
        r"%LOCALAPPDATA%\BraveSoftware\Brave-Browser\Application\brave.exe",
    ],
    OPERA: [
        r"%LOCALAPPDATA%\Programs\Opera\opera.exe",
        r"C:\Program Files\Opera\opera.exe",
        r"C:\Program Files (x86)\Opera\opera.exe",
    ],
    OPERA_GX: [
        r"%LOCALAPPDATA%\Programs\Opera GX\opera.exe",
        r"C:\Program Files\Opera GX\opera.exe",
        r"C:\Program Files (x86)\Opera GX\opera.exe",
    ],
}

_MACOS_EXES = {
    CHROME: ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"],
    EDGE: ["/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"],
    BRAVE: ["/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"],
    OPERA: ["/Applications/Opera.app/Contents/MacOS/Opera"],
    OPERA_GX: ["/Applications/Opera GX.app/Contents/MacOS/Opera"],
}

_LINUX_EXES = {
    CHROME: [
        "/usr/bin/google-chrome",
        "/usr/bin/google-chrome-stable",
        "/opt/google/chrome/chrome",
    ],
    EDGE: [
        "/usr/bin/microsoft-edge",
        "/usr/bin/microsoft-edge-stable",
        "/opt/microsoft/msedge/msedge",
    ],
    BRAVE: [
        "/usr/bin/brave-browser",
        "/usr/bin/brave",
        "/opt/brave.com/brave/brave-browser",
        "/opt/brave.com/brave/brave",
    ],
    # Opera GX has no Linux build; only plain Opera is listed here.
    OPERA: ["/usr/bin/opera", "/usr/lib/x86_64-linux-gnu/opera/opera"],
}


def executable_candidates(value: str | None) -> list[str]:
    """Install locations to try for this browser on the current OS, most likely first."""
    browser = normalize(value)
    if sys.platform == "win32":
        table = _WINDOWS_EXES
    elif sys.platform == "darwin":
        table = _MACOS_EXES
    else:
        table = _LINUX_EXES
    return [os.path.expandvars(p) for p in table.get(browser, [])]


def find_executable(value: str | None) -> str | None:
    """First install location that actually exists, or None."""
    for candidate in executable_candidates(value):
        if os.path.exists(candidate):
            return candidate
    return None


# ------------------------------------------------------- Per-browser caveats

# Shown next to the browser picker when non-empty: things that work
# differently here than on the other browsers. Kept to one sentence.
COMPATIBILITY_NOTES = {
    BRAVE: (
        "Launched from its standard install path, so a Brave installed somewhere "
        "unusual won't be found."
    ),
    OPERA: (
        "Opera's own start page stays open in the joined window - it can't be "
        "closed automatically."
    ),
    OPERA_GX: (
        "The GX Corner tab stays open in the joined window - it can't be closed "
        "automatically."
    ),
}


def compatibility_note(value: str | None) -> str:
    return COMPATIBILITY_NOTES.get(normalize(value), "")


def resolve(meeting_browser: str | None, connection: dict | None = None) -> str:
    """The browser a join should actually drive.

    A named connection is tied to one specific browser install and profile,
    so it wins over the meeting's own field; the meeting field is what the
    isolated-profile path (no connection) uses.
    """
    if connection and connection.get("browser"):
        return normalize(connection["browser"])
    return normalize(meeting_browser)
