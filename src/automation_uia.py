"""
Joins a Google Meet using Windows UI Automation - the OS-level
accessibility API - rather than the browser's remote-debugging protocol,
which Chrome refuses to expose for your real profile as of Chrome 136.

Two ways to get a window to work with:
1. LAUNCH mode (default): given a profile_directory, runs the browser's exe
   for that profile with the link. Works whether it's already open or not.
2. ATTACH mode: with no profile_directory, finds an already-open window of
   that browser (optionally matched by title) and opens a new one from it via
   Ctrl+N. Still reachable for connections saved without a profile.

Every browser-specific value (exe path, window class, process image) comes
from browsers.py; the flow itself is identical for all of them.

Windows-only. Requires pywinauto (and its pywin32 dependency).
"""
from __future__ import annotations

import os
import subprocess
import time

from . import browsers, paths
from .logging_setup import get_logger
from .models import JoinResult

LOG_DIR = paths.LOG_DIR

logger = get_logger()

MIC_OFF_LABELS = ["Turn off microphone"]
CAM_OFF_LABELS = ["Turn off camera"]
# Meet relabels the toggle once it's off, so finding these is the proof that
# muting took effect. "Turn on microphone" is not a substring of "Turn off
# microphone", so the contains-match used below can't confuse the two.
MIC_CONFIRM_LABELS = ["Turn on microphone"]
CAM_CONFIRM_LABELS = ["Turn on camera"]
JOIN_LABELS = ["Join now", "Ask to join"]

# Extra attempts per control before giving up and joining anyway.
VERIFY_RETRIES = 2
DISMISS_LABELS = [
    "Got it", "Dismiss", "Close", "No thanks",
    "Continue without microphone", "Continue without camera",
    "Use without an account", "Allow",
]

_last_meet_window_handles: dict[str, int] = {}

# PROCESS_QUERY_LIMITED_INFORMATION - enough to read another process's image
# path, and granted for same-user processes without elevation.
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


def _window_process_path(handle) -> str | None:
    """Full exe path owning this window, or None if unreadable.

    The whole path, not just the file name: Opera and Opera GX are both
    opera.exe and can only be told apart by where they're installed.
    """
    try:
        import win32api
        import win32process

        _, pid = win32process.GetWindowThreadProcessId(handle)
        process = win32api.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        try:
            return win32process.GetModuleFileNameEx(process, 0)
        finally:
            win32api.CloseHandle(process)
    except Exception:  # noqa: BLE001 - identification is best-effort
        return None


def _window_belongs_to(handle, browser: str) -> bool:
    """Whether this window is really one of `browser`'s.

    Chrome_WidgetWin_1 is shared by every Chromium browser *and* every Electron
    app (VS Code, Discord), so the class alone can't tell Chrome from Edge. The
    owning process can.
    """
    if not browsers.process_images(browser):
        return True
    path = _window_process_path(handle)
    if path is None:
        # Unreadable owner (rare). Chrome keeps its historic permissive
        # behaviour; another browser must not grab an unidentifiable window.
        return browsers.is_chrome(browser)
    return browsers.matches_executable(browser, path)


_logged_window_classes: set[str] = set()


def _windows_owned_by(browser: str, class_name: str | None) -> list:
    """Top-level windows owned by this browser, optionally class-filtered."""
    from pywinauto import Desktop

    desktop = Desktop(backend="uia")
    found = desktop.windows(class_name=class_name) if class_name else desktop.windows()
    windows = []
    for w in found:
        try:
            if _window_belongs_to(w.handle, browser):
                windows.append(w)
        except Exception:  # noqa: BLE001 - some windows vanish mid-enum
            continue
    return windows


def _browser_windows(browser: str) -> list:
    """Every open top-level window belonging to this browser.

    The class filter is only a speed-up. For a browser whose window class
    hasn't been confirmed on a live window, an empty result falls back to a
    sweep of every top-level window matched on the owning process - so a
    wrong class guess degrades to "slightly slower", never "finds nothing".
    """
    try:
        windows = _windows_owned_by(browser, browsers.window_class(browser))
        if not windows and not browsers.window_class_is_verified(browser):
            windows = _windows_owned_by(browser, None)
            _log_observed_classes(browser, windows)
        return windows
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Could not enumerate {browsers.short_name(browser)} windows: {e}")
        return []


def _log_observed_classes(browser: str, windows: list) -> None:
    """Record the real window class the first time one turns up this way."""
    for w in windows:
        try:
            import win32gui
            observed = win32gui.GetClassName(w.handle)
        except Exception:  # noqa: BLE001
            continue
        key = f"{browser}:{observed}"
        if key not in _logged_window_classes:
            _logged_window_classes.add(key)
            logger.info(
                f"{browsers.short_name(browser)} window class is '{observed}' "
                f"(expected '{browsers.window_class(browser)}'); found via the "
                "process-based fallback sweep"
            )


def _close_previous_window(key: str, browser: str = browsers.DEFAULT) -> None:
    handle = _last_meet_window_handles.pop(key, None)
    if handle is None:
        return
    try:
        for w in _browser_windows(browser):
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
    """Reduce a pasted 'Profile Path' (chrome://version and friends) to its last folder."""
    value = value.strip().strip('"').rstrip("\\/")
    if "\\" in value or "/" in value:
        normalized = value.replace("/", "\\").split("\\")[-1]
        logger.info(f"Profile directory looked like a full path ('{value}'); using '{normalized}' instead")
        return normalized
    return value


def normalize_profile_setting(value: str, browser: str = browsers.DEFAULT) -> str:
    """Clean up whatever the profile field holds for this browser.

    Chromium browsers store a folder *name* inside User Data, so a pasted full
    path gets reduced to its last folder. Opera stores the full path of a whole
    profile folder, which must survive intact.
    """
    if browsers.uses_single_profile_dir(browser):
        return value.strip().strip('"').rstrip("\\/")
    return normalize_profile_directory(value)


def _find_browser_exe(browser: str = browsers.DEFAULT) -> str | None:
    return browsers.find_executable(browser)


def list_browser_windows(browser: str = browsers.DEFAULT) -> list[str]:
    """Titles of this browser's open windows (Chrome unless told otherwise)."""
    if not _require_pywinauto():
        return []
    titles = []
    for w in _browser_windows(browser):
        try:
            t = w.window_text()
            if t:
                titles.append(t)
        except Exception:  # noqa: BLE001 - some windows vanish mid-enum
            continue
    return titles


def _browser_window_handles(browser: str = browsers.DEFAULT) -> set:
    handles = set()
    for w in _browser_windows(browser):
        try:
            handles.add(w.handle)
        except Exception:  # noqa: BLE001
            continue
    return handles


def _wait_for_new_window(before_handles: set, timeout_s: float = 5.0,
                         browser: str = browsers.DEFAULT):
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        for w in _browser_windows(browser):
            try:
                if w.handle not in before_handles:
                    return w
            except Exception:  # noqa: BLE001
                continue
        time.sleep(0.2)
    return None


def _foreground_browser_window(browser: str = browsers.DEFAULT):
    try:
        import win32gui
        from pywinauto import Desktop
        hwnd = win32gui.GetForegroundWindow()
        if not hwnd:
            return None
        # The class check is just a cheap pre-filter, and only trustworthy for
        # a browser whose class was confirmed live; ownership is the real test.
        if (browsers.window_class_is_verified(browser)
                and win32gui.GetClassName(hwnd) != browsers.window_class(browser)):
            return None
        if not _window_belongs_to(hwnd, browser):
            return None
        return Desktop(backend="uia").window(handle=hwnd)
    except Exception:  # noqa: BLE001
        return None


def _wait_for_target_window(before_handles: set, timeout_s: float,
                            browser: str = browsers.DEFAULT):
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        handles = _browser_window_handles(browser)
        new_handles = handles - before_handles
        if new_handles:
            for w in _browser_windows(browser):
                try:
                    if w.handle in new_handles:
                        return w, "new_window"
                except Exception:  # noqa: BLE001
                    continue
        fg = _foreground_browser_window(browser)
        if fg is not None:
            try:
                if fg.handle in before_handles:
                    return fg, "reused_window"
            except Exception:  # noqa: BLE001
                pass
        time.sleep(0.3)
    return None, None


def _find_window(title_hint: str | None, browser: str = browsers.DEFAULT):
    candidates = _browser_windows(browser)
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


def _turn_off_control_uia(
    window,
    what: str,
    off_labels: list[str],
    confirm_labels: list[str],
    control_timeout_s: int,
    verify: bool,
) -> bool:
    """Click a control off and read the tree back to confirm it went off.

    click_input() moves the real cursor, so a click can land on a control
    that has just shifted, or arrive while the page is still settling. The
    state is read back rather than assumed - and only a control still
    offering "Turn off ..." is clicked again, since re-clicking one that
    already went off would turn it back on.
    """
    btn = _find_button_by_names(window, off_labels, control_timeout_s)
    if btn:
        btn.click_input()
        logger.info(f"Clicked {what.lower()} toggle (UI Automation)")
    else:
        logger.warning(
            f"{what} toggle not found via UI Automation (may already be off, or selector drifted)")

    if not verify:
        return bool(btn)

    for attempt in range(VERIFY_RETRIES + 1):
        if _find_button_by_names(window, confirm_labels, timeout_s=2):
            logger.info(f"Verified {what.lower()} is off")
            return True
        if attempt == VERIFY_RETRIES:
            break
        logger.warning(f"{what} still on after attempt {attempt + 1}; trying again")
        retry = _find_button_by_names(window, off_labels, timeout_s=3)
        if retry:
            retry.click_input()

    logger.warning(f"Could not confirm {what.lower()} is off - joining anyway")
    return False


def join_google_meet_uia(
    link: str,
    mute_mic: bool = True,
    mute_camera: bool = True,
    profile_directory: str | None = None,
    title_hint: str | None = None,
    nav_timeout_s: int = 45,
    control_timeout_s: int = 15,
    browser: str = browsers.DEFAULT,
    verify_controls: bool = True,
) -> JoinResult:
    if not _require_pywinauto():
        return JoinResult(
            success=False,
            message="pywinauto is not installed. Run: pip install pywinauto pywin32",
        )

    browser = browsers.normalize(browser)
    label = browsers.short_name(browser)
    exe_name = (browsers.process_images(browser) or ("the browser",))[0]
    version_page = browsers.version_page(browser)

    # Keyed by browser too: an Edge and a Chrome connection naming the same
    # profile folder are still two different windows to track.
    connection_key = f"{browser}:{profile_directory or title_hint or '_default_'}"
    needs_manual_navigation = True  # launch mode navigates itself; Ctrl+N doesn't
    how = "new_window"  # Ctrl+N always makes one; launch mode overrides this below

    try:
        _close_previous_window(connection_key, browser)
        before_handles = _browser_window_handles(browser)

        if profile_directory:
            profile_directory = normalize_profile_setting(profile_directory, browser)
            browser_exe = _find_browser_exe(browser)
            if not browser_exe:
                return JoinResult(
                    success=False,
                    message=f"Could not find {exe_name} in standard install locations.",
                )
            logger.info(
                f"Launching {label} profile '{profile_directory}' with the meeting link "
                f"directly ({label} decides: new tab if already open, new window if not)"
            )
            # --profile-directory for Chromium's named profiles, --user-data-dir
            # for Opera's one-folder-per-install layout.
            subprocess.Popen([
                browser_exe,
                *browsers.profile_launch_args(browser, profile_directory),
                link,
            ])
            meet_window, how = _wait_for_target_window(
                before_handles, timeout_s=nav_timeout_s, browser=browser
            )
            if meet_window is None:
                what = ("profile folder path" if browsers.uses_single_profile_dir(browser)
                        else "profile directory name")
                return JoinResult(
                    success=False,
                    message=(
                        f"{label} for profile '{profile_directory}' did not respond in time. "
                        f"Double check the {what} via {version_page}."
                    ),
                )
            logger.info(
                f"Got target window via '{how}' "
                f"({'reused your already-open profile, new tab' if how == 'reused_window' else 'fresh window, profile was closed'})"
            )
            needs_manual_navigation = False  # Chrome already loaded the link for us
        else:
            # Attach mode: spawn a new window from an existing one via
            # Ctrl+N. Requires the browser to already be open and matching.
            source = _find_window(title_hint, browser)
            if source is None:
                return JoinResult(
                    success=False,
                    message=(
                        f"No open {label} window found"
                        + (f" matching '{title_hint}'" if title_hint else "")
                        + ", and no profile directory is configured to launch one. "
                        "Add a profile directory to this connection for a more "
                        f"reliable setup that doesn't depend on {label} already being open."
                    ),
                )
            logger.info(f"Attaching to existing {label} window via UI Automation: '{source.window_text()}'")
            source.set_focus()
            time.sleep(0.3)
            source.type_keys("^n", pause=0.05)
            meet_window = _wait_for_new_window(before_handles, timeout_s=5.0, browser=browser)
            if meet_window is None:
                return JoinResult(success=False, message=f"New {label} window did not appear in time.")

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
            _turn_off_control_uia(window, "Microphone", MIC_OFF_LABELS, MIC_CONFIRM_LABELS,
                                  control_timeout_s, verify_controls)

        if mute_camera:
            _turn_off_control_uia(window, "Camera", CAM_OFF_LABELS, CAM_CONFIRM_LABELS,
                                  control_timeout_s, verify_controls)

        _find_button_by_names(window, DISMISS_LABELS, timeout_s=2)

        # Dismissing a dialog can hand focus back to a control and flip it on,
        # so anything that drifted gets one more correction before joining.
        if verify_controls:
            if mute_mic and not _find_button_by_names(window, MIC_CONFIRM_LABELS, timeout_s=1):
                logger.warning("Microphone came back on before joining; correcting")
                _turn_off_control_uia(window, "Microphone", MIC_OFF_LABELS, MIC_CONFIRM_LABELS,
                                      control_timeout_s, verify_controls)
            if mute_camera and not _find_button_by_names(window, CAM_CONFIRM_LABELS, timeout_s=1):
                logger.warning("Camera came back on before joining; correcting")
                _turn_off_control_uia(window, "Camera", CAM_OFF_LABELS, CAM_CONFIRM_LABELS,
                                      control_timeout_s, verify_controls)

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
