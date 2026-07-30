"""
Joins a Google Meet using Windows UI Automation - the OS-level
accessibility API - rather than Chrome's remote-debugging protocol, which
Chrome refuses to expose for your real profile as of Chrome 136.

Two ways to get a window to work with:
1. LAUNCH mode (default): given a profile_directory, runs chrome.exe for
   that profile with the link. Works whether Chrome is already open or not.
2. ATTACH mode: with no profile_directory, finds an already-open Chrome
   window (optionally matched by title) and opens a new one from it via
   Ctrl+N. Still reachable for connections saved without a profile.

Windows-only. Requires pywinauto (and its pywin32 dependency).
"""
from __future__ import annotations

import os
import subprocess
import time

from . import paths
from .logging_setup import get_logger
from .models import JoinResult

LOG_DIR = paths.LOG_DIR

logger = get_logger()

MIC_OFF_LABELS = ["Turn off microphone"]
CAM_OFF_LABELS = ["Turn off camera"]
JOIN_LABELS = ["Join now", "Ask to join"]
DISMISS_LABELS = [
    "Got it", "Dismiss", "Close", "No thanks",
    "Continue without microphone", "Continue without camera",
    "Use without an account", "Allow",
]

CHROME_CANDIDATE_PATHS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
]

_last_meet_window_handles: dict[str, int] = {}


def _close_previous_window(key: str) -> None:
    handle = _last_meet_window_handles.pop(key, None)
    if handle is None:
        return
    try:
        from pywinauto import Desktop
        for w in Desktop(backend="uia").windows(class_name="Chrome_WidgetWin_1"):
            try:
                if w.handle == handle:
                    w.close()
                    logger.info(f"Closed previous auto-join window for '{key}'")
                    return
            except Exception:
                continue
    except Exception as e:
        logger.warning(f"Could not close previous auto-join window: {e}")


def _require_pywinauto():
    try:
        import pywinauto
        return True
    except ImportError:
        return False


def normalize_profile_directory(value: str) -> str:
    """Reduce a pasted Chrome 'Profile Path' to just its last folder name."""
    value = value.strip().strip('"').rstrip("\\/")
    if "\\" in value or "/" in value:
        normalized = value.replace("/", "\\").split("\\")[-1]
        logger.info(f"Profile directory looked like a full path ('{value}'); using '{normalized}' instead")
        return normalized
    return value


def _find_chrome_exe() -> str | None:
    for p in CHROME_CANDIDATE_PATHS:
        if os.path.exists(p):
            return p
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    if local_app_data:
        candidate = os.path.join(local_app_data, "Google", "Chrome", "Application", "chrome.exe")
        if os.path.exists(candidate):
            return candidate
    return None


def list_chrome_windows() -> list[str]:
    if not _require_pywinauto():
        return []
    from pywinauto import Desktop
    titles = []
    try:
        for w in Desktop(backend="uia").windows(class_name="Chrome_WidgetWin_1"):
            try:
                t = w.window_text()
                if t:
                    titles.append(t)
            except Exception:  # noqa: BLE001 - some windows vanish mid-enum
                continue
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Could not enumerate Chrome windows: {e}")
    return titles


def _chrome_window_handles() -> set:
    from pywinauto import Desktop
    handles = set()
    try:
        for w in Desktop(backend="uia").windows(class_name="Chrome_WidgetWin_1"):
            try:
                handles.add(w.handle)
            except Exception:  # noqa: BLE001
                continue
    except Exception:  # noqa: BLE001
        pass
    return handles


def _wait_for_new_window(before_handles: set, timeout_s: float = 5.0):
    from pywinauto import Desktop
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            for w in Desktop(backend="uia").windows(class_name="Chrome_WidgetWin_1"):
                try:
                    if w.handle not in before_handles:
                        return w
                except Exception:  # noqa: BLE001
                    continue
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.2)
    return None


def _foreground_chrome_window():
    try:
        import win32gui
        from pywinauto import Desktop
        hwnd = win32gui.GetForegroundWindow()
        if not hwnd or win32gui.GetClassName(hwnd) != "Chrome_WidgetWin_1":
            return None
        return Desktop(backend="uia").window(handle=hwnd)
    except Exception:  # noqa: BLE001
        return None


def _wait_for_target_window(before_handles: set, timeout_s: float):
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        handles = _chrome_window_handles()
        new_handles = handles - before_handles
        if new_handles:
            from pywinauto import Desktop
            for w in Desktop(backend="uia").windows(class_name="Chrome_WidgetWin_1"):
                try:
                    if w.handle in new_handles:
                        return w, "new_window"
                except Exception:  # noqa: BLE001
                    continue
        fg = _foreground_chrome_window()
        if fg is not None:
            try:
                if fg.handle in before_handles:
                    return fg, "reused_window"
            except Exception:  # noqa: BLE001
                pass
        time.sleep(0.3)
    return None, None


def _find_window(title_hint: str | None):
    from pywinauto import Desktop
    desktop = Desktop(backend="uia")
    candidates = desktop.windows(class_name="Chrome_WidgetWin_1")
    if not candidates:
        return None
    if not title_hint:
        return candidates[0]
    for w in candidates:
        try:
            if title_hint.lower() in w.window_text().lower():
                return w
        except Exception:  # noqa: BLE001
            continue
    return None


def _set_clipboard(text: str) -> None:
    import win32clipboard
    win32clipboard.OpenClipboard()
    try:
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardText(text)
    finally:
        win32clipboard.CloseClipboard()


def _find_button_by_names(window, names: list[str], timeout_s: int):
    """Poll the window's accessibility tree for a button matching one of
    these names. Chrome populates that tree after the page looks loaded,
    so this has to wait rather than check once."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            for btn in window.descendants(control_type="Button"):
                try:
                    text = (btn.window_text() or "") + " " + (btn.element_info.name or "")
                except Exception:  # noqa: BLE001
                    continue
                for name in names:
                    if name.lower() in text.lower():
                        return btn
        except Exception:  # noqa: BLE001 - tree can be transiently unstable while loading
            pass
        time.sleep(0.5)
    return None


def join_google_meet_uia(
    link: str,
    mute_mic: bool = True,
    mute_camera: bool = True,
    profile_directory: str | None = None,
    title_hint: str | None = None,
    nav_timeout_s: int = 45,
    control_timeout_s: int = 15,
) -> JoinResult:
    if not _require_pywinauto():
        return JoinResult(
            success=False,
            message="pywinauto is not installed. Run: pip install pywinauto pywin32",
        )

    connection_key = profile_directory or title_hint or "_default_"
    needs_manual_navigation = True  # launch mode navigates itself; Ctrl+N doesn't
    how = "new_window"  # Ctrl+N always makes one; launch mode overrides this below

    try:
        _close_previous_window(connection_key)
        before_handles = _chrome_window_handles()

        if profile_directory:
            profile_directory = normalize_profile_directory(profile_directory)
            chrome_exe = _find_chrome_exe()
            if not chrome_exe:
                return JoinResult(
                    success=False,
                    message="Could not find chrome.exe in standard install locations.",
                )
            logger.info(
                f"Launching Chrome profile '{profile_directory}' with the meeting link "
                "directly (Chrome decides: new tab if already open, new window if not)"
            )
            subprocess.Popen([
                chrome_exe,
                f"--profile-directory={profile_directory}",
                link,
            ])
            meet_window, how = _wait_for_target_window(before_handles, timeout_s=nav_timeout_s)
            if meet_window is None:
                return JoinResult(
                    success=False,
                    message=(
                        f"Chrome for profile '{profile_directory}' did not respond in time. "
                        "Double check the profile directory name via chrome://version."
                    ),
                )
            logger.info(
                f"Got target window via '{how}' "
                f"({'reused your already-open profile, new tab' if how == 'reused_window' else 'fresh window, profile was closed'})"
            )
            needs_manual_navigation = False  # Chrome already loaded the link for us
        else:
            # Attach mode: spawn a new window from an existing one via
            # Ctrl+N. Requires Chrome to already be open and matching.
            source = _find_window(title_hint)
            if source is None:
                return JoinResult(
                    success=False,
                    message=(
                        "No open Chrome window found"
                        + (f" matching '{title_hint}'" if title_hint else "")
                        + ", and no profile directory is configured to launch one. "
                        "Add a profile directory to this connection for a more "
                        "reliable setup that doesn't depend on Chrome already being open."
                    ),
                )
            logger.info(f"Attaching to existing Chrome window via UI Automation: '{source.window_text()}'")
            source.set_focus()
            time.sleep(0.3)
            source.type_keys("^n", pause=0.05)
            meet_window = _wait_for_new_window(before_handles, timeout_s=5.0)
            if meet_window is None:
                return JoinResult(success=False, message="New Chrome window did not appear in time.")

        meet_window.set_focus()
        time.sleep(0.5)

        if needs_manual_navigation or how != "reused_window":
            try:
                meet_window.move_window(x=40, y=40, width=900, height=650)
            except Exception:  # noqa: BLE001 - purely cosmetic, never fatal
                pass

        if needs_manual_navigation:
            _set_clipboard(link)
            meet_window.type_keys("^v", pause=0.05)
            meet_window.type_keys("{ENTER}", pause=0.05)
            logger.info(f"Navigated to {link} via UI Automation (dedicated window)")

        window = meet_window

        # Only windows this app created are tracked for auto-close before
        # the next join. If Chrome reused an already-open window instead,
        # it holds the user's own tabs and must never be closed for them.
        if how == "new_window":
            try:
                _last_meet_window_handles[connection_key] = meet_window.handle
            except Exception:  # noqa: BLE001 - tracking is best-effort, never fatal
                pass
        else:
            logger.info(
                "Joined via a tab in your already-open window - not tracking it for "
                "auto-close, since it's your window, not one this app created."
            )

        # The accessibility tree lags behind the visual page load.
        time.sleep(3)

        _find_button_by_names(window, DISMISS_LABELS, timeout_s=2)

        if mute_mic:
            btn = _find_button_by_names(window, MIC_OFF_LABELS, control_timeout_s)
            if btn:
                btn.click_input()
                logger.info("Clicked microphone toggle (UI Automation)")
            else:
                logger.warning("Mic toggle not found via UI Automation (may already be off, or selector drifted)")

        if mute_camera:
            btn = _find_button_by_names(window, CAM_OFF_LABELS, control_timeout_s)
            if btn:
                btn.click_input()
                logger.info("Clicked camera toggle (UI Automation)")
            else:
                logger.warning("Camera toggle not found via UI Automation (may already be off, or selector drifted)")

        _find_button_by_names(window, DISMISS_LABELS, timeout_s=2)

        join_btn = _find_button_by_names(window, JOIN_LABELS, control_timeout_s)
        if not join_btn:
            screenshot_path = str(LOG_DIR / f"join_failed_uia_{int(time.time())}.png")
            try:
                window.capture_as_image().save(screenshot_path)
            except Exception:  # noqa: BLE001
                screenshot_path = None
            return JoinResult(
                success=False,
                message="Could not find the Join now / Ask to join button.",
                screenshot_path=screenshot_path,
            )

        join_btn.click_input()
        logger.info("Successfully clicked join control (UI Automation)")
        return JoinResult(success=True, message="Joined successfully.")

    except Exception as e:  # noqa: BLE001
        logger.exception("Unexpected UI Automation error")
        return JoinResult(success=False, message=f"Automation error: {e}")
