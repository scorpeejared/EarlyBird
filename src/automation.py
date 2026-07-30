"""
Playwright browser automation for auto-joining Google Meet calls.

Used for the isolated profile and for "debug port" (CDP) connections;
Windows UI Automation handles the rest, in automation_uia.py.

Every interaction is selector-based (accessible role + name) rather than
a pixel coordinate, so it survives resolution changes and Meet redesigns.
"""
from __future__ import annotations

import time

from playwright.sync_api import (
    sync_playwright,
    Page,
    BrowserContext,
    TimeoutError as PWTimeoutError,
)

from . import paths
from .logging_setup import get_logger
from .models import JoinResult

LOG_DIR = paths.LOG_DIR
PROFILE_DIR = paths.PROFILE_DIR

logger = get_logger()

# Lists, because Google occasionally A/B tests different label wording.
MIC_OFF_LABELS = ["Turn off microphone"]
CAM_OFF_LABELS = ["Turn off camera"]
JOIN_LABELS = ["Join now", "Ask to join"]
DISMISS_LABELS = ["Got it", "Dismiss", "Close", "No thanks"]


def _try_click_by_role(page: Page, role: str, names: list[str], timeout_ms: int = 4000) -> bool:
    """Click the first control matching any of these accessible names."""
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
    """The on-page steps shared by both launch modes: navigate, dismiss
    popups, mute mic/camera, click Join."""
    logger.info(f"Navigating to {link}")
    page.goto(link, wait_until="domcontentloaded", timeout=nav_timeout_s * 1000)

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
                try:
                    context.grant_permissions(["camera", "microphone"])
                except Exception:  # noqa: BLE001 - some Chrome builds restrict this; not fatal
                    logger.warning("Could not grant camera/mic permissions on attached context")

                page = context.new_page()
                page.set_default_timeout(control_timeout_s * 1000)
                page.bring_to_front()
                # Other pages stay open here: this is the user's own
                # browser session, full of their tabs.
                return _run_join_flow(page, link, mute_mic, mute_camera, nav_timeout_s, control_timeout_s)

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
