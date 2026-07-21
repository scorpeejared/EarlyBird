"""
Browser automation for auto-joining Google Meet calls.

Design choices (see README for the full reasoning):
- Playwright, not Selenium/PyAutoGUI: best selector engine, built-in waits,
  and it can grant camera/mic permissions at the API level so Chrome never
  shows a permission popup in the first place.
- channel="chrome" + a persistent user_data_dir: reuses your real, installed
  Chrome and keeps you logged into Google between runs, so there's no
  sign-in step to automate.
- Every interaction is selector-based (accessible role + name), never a
  fixed pixel coordinate, so it keeps working across screen resolutions,
  window sizes, and minor Meet redesigns.
- A PyAutoGUI fallback hook exists for the rare case a selector can't be
  found at all (e.g. Google changed the DOM) - see try_pyautogui_fallback().
  It's opt-in and off by default.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path

from playwright.sync_api import (
    sync_playwright,
    Page,
    BrowserContext,
    TimeoutError as PWTimeoutError,
)

LOG_DIR = Path(__file__).parent.parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
PROFILE_DIR = Path(__file__).parent.parent.parent / "chrome_profile"

logging.basicConfig(
    filename=LOG_DIR / "automation.log",
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("meet_automation")


@dataclass
class JoinResult:
    success: bool
    message: str
    screenshot_path: str | None = None


# Accessible names Google Meet has used for these controls. Kept as a list
# because Google occasionally A/B tests slightly different label wording -
# trying several candidates is more robust than hardcoding one string.
MIC_OFF_LABELS = ["Turn off microphone"]
CAM_OFF_LABELS = ["Turn off camera"]
JOIN_LABELS = ["Join now", "Ask to join"]
DISMISS_LABELS = ["Got it", "Dismiss", "Close", "No thanks"]


def _try_click_by_role(page: Page, role: str, names: list[str], timeout_ms: int = 4000) -> bool:
    """Try clicking the first matching accessible-role/name control.

    This is the reliability workhorse: instead of page.click(x, y) we ask
    the browser's accessibility tree for "the button named X", which is
    stable across resolutions, zoom levels, and most redesigns.
    """
    for name in names:
        try:
            locator = page.get_by_role(role, name=name, exact=False)
            locator.wait_for(state="visible", timeout=timeout_ms)
            locator.first.click(timeout=timeout_ms)
            logger.info(f"Clicked {role} '{name}'")
            return True
        except PWTimeoutError:
            continue
    return False


def _dismiss_popups(page: Page) -> None:
    """Best-effort dismissal of any 'tips' or informational dialogs Meet shows."""
    _try_click_by_role(page, "button", DISMISS_LABELS, timeout_ms=1500)


def _run_join_flow(
    page: Page,
    link: str,
    mute_mic: bool,
    mute_camera: bool,
    nav_timeout_s: int,
    control_timeout_s: int,
) -> JoinResult:
    """The actual on-page steps, shared by both launch modes below:
    navigate, dismiss popups, mute mic/camera, click Join."""
    logger.info(f"Navigating to {link}")
    page.goto(link, wait_until="domcontentloaded", timeout=nav_timeout_s * 1000)

    # Give the SPA a moment to render the join-preview screen, then wait
    # specifically for a control we expect, rather than a blind sleep -
    # this is the "wait for load" step done properly.
    page.wait_for_load_state("networkidle", timeout=nav_timeout_s * 1000)
    _dismiss_popups(page)

    if mute_mic:
        if not _try_click_by_role(page, "button", MIC_OFF_LABELS, control_timeout_s * 1000):
            logger.warning("Mic toggle not found (may already be off, or selector drifted)")

    if mute_camera:
        if not _try_click_by_role(page, "button", CAM_OFF_LABELS, control_timeout_s * 1000):
            logger.warning("Camera toggle not found (may already be off, or selector drifted)")

    _dismiss_popups(page)

    joined = _try_click_by_role(page, "button", JOIN_LABELS, control_timeout_s * 1000)
    if not joined:
        screenshot_path = str(LOG_DIR / f"join_failed_{int(time.time())}.png")
        page.screenshot(path=screenshot_path)
        return JoinResult(
            success=False,
            message="Could not find the Join now / Ask to join button. "
                    "Screenshot saved for debugging.",
            screenshot_path=screenshot_path,
        )

    logger.info("Successfully clicked join control")
    return JoinResult(success=True, message="Joined successfully.")


def join_google_meet(
    link: str,
    mute_mic: bool = True,
    mute_camera: bool = True,
    headless: bool = False,
    nav_timeout_s: int = 45,
    control_timeout_s: int = 15,
    user_data_dir: str | None = None,
    profile_directory: str | None = None,
    use_running_chrome: bool = False,
    cdp_port: int = 9222,
) -> JoinResult:
    try:
        with sync_playwright() as p:
            if use_running_chrome:
                logger.info(f"Attaching to already-running Chrome on port {cdp_port}")
                try:
                    browser = p.chromium.connect_over_cdp(f"http://localhost:{cdp_port}")
                except Exception as e:
                    logger.error(f"Could not attach to Chrome on port {cdp_port}: {e}")
                    return JoinResult(
                        success=False,
                        message=(
                            f"Could not connect to Chrome on port {cdp_port}. "
                            "Make sure Chrome was started with the debug launcher "
                            "(launch_chrome_debug script), not a normal shortcut."
                        ),
                    )
                context = browser.contexts[0] if browser.contexts else browser.new_context()
                # Permissions can still be granted on an already-open context.
                try:
                    context.grant_permissions(["camera", "microphone"])
                except Exception:  # noqa: BLE001 - some Chrome builds restrict this; not fatal
                    logger.warning("Could not grant camera/mic permissions on attached context")

                page = context.new_page()
                page.set_default_timeout(control_timeout_s * 1000)
                page.bring_to_front()
                # Deliberately do NOT close other pages here - unlike the
                # launch modes below, this is the user's live, everyday
                # browser session, full of their own tabs we must not touch.
                result = _run_join_flow(page, link, mute_mic, mute_camera, nav_timeout_s, control_timeout_s)
                return result

            # --- Launch modes (isolated profile or a real profile folder) ---
            resolved_dir = user_data_dir or str(PROFILE_DIR)
            logger.info(
                f"Launching Chrome with user_data_dir='{resolved_dir}' "
                f"profile_directory='{profile_directory or '(default)'}'"
            )
            launch_args = ["--disable-notifications"]
            if profile_directory:
                launch_args.append(f"--profile-directory={profile_directory}")

            context: BrowserContext = p.chromium.launch_persistent_context(
                user_data_dir=resolved_dir,
                channel="chrome",
                headless=headless,
                permissions=["camera", "microphone"],
                args=launch_args,
            )
            page = context.new_page()
            page.set_default_timeout(control_timeout_s * 1000)

            for other_page in list(context.pages):
                if other_page is not page:
                    try:
                        other_page.close()
                    except Exception:  # noqa: BLE001 - best-effort cleanup only
                        pass
            page.bring_to_front()

            return _run_join_flow(page, link, mute_mic, mute_camera, nav_timeout_s, control_timeout_s)

    except PWTimeoutError as e:
        logger.error(f"Timeout joining meeting: {e}")
        return JoinResult(success=False, message=f"Timed out waiting for Meet to load: {e}")
    except Exception as e:  # noqa: BLE001 - surface any automation error to the scheduler
        logger.exception("Unexpected automation error")
        return JoinResult(success=False, message=f"Automation error: {e}")


def try_pyautogui_fallback(x: int, y: int) -> None:
    import pyautogui
    pyautogui.click(x, y)
