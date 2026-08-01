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

from . import browsers, paths
from .logging_setup import get_logger
from .models import JoinResult

LOG_DIR = paths.LOG_DIR
PROFILE_DIR = paths.PROFILE_DIR

logger = get_logger()

# Lists, because Google occasionally A/B tests different label wording.
MIC_OFF_LABELS = ["Turn off microphone"]
CAM_OFF_LABELS = ["Turn off camera"]
# Meet relabels the toggle once it's off, so the presence of these is the
# proof that muting actually took effect - the click landing isn't proof.
MIC_CONFIRM_LABELS = ["Turn on microphone"]
CAM_CONFIRM_LABELS = ["Turn on camera"]
JOIN_LABELS = ["Join now", "Ask to join"]
DISMISS_LABELS = ["Got it", "Dismiss", "Close", "No thanks"]

# How many extra attempts the verification pass gets per control before it
# gives up and joins anyway. Joining muted-but-unverified beats not joining.
VERIFY_RETRIES = 2


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


def _control_is_off(page: Page, confirm_labels: list[str], timeout_ms: int = 1500) -> bool:
    """True once the toggle offers to turn the control back ON - i.e. it's off."""
    for name in confirm_labels:
        try:
            locator = page.get_by_role("button", name=name, exact=False)
            locator.first.wait_for(state="visible", timeout=timeout_ms)
            return True
        except PWTimeoutError:
            continue
    return False


def _turn_off_control(
    page: Page,
    what: str,
    off_labels: list[str],
    confirm_labels: list[str],
    control_timeout_s: int,
    verify: bool,
) -> bool:
    """Turn a control off and confirm it really went off, retrying if not.

    A click that lands is not proof: Meet can swallow it while the page is
    still settling, which is how someone ends up joining unmuted. So the
    state is read back, and only a control still showing "Turn off ..." is
    clicked again - re-clicking a control that already went off would turn
    it back on.
    """
    clicked = _try_click_by_role(page, "button", off_labels, control_timeout_s * 1000)
    if not clicked:
        logger.warning(f"{what} toggle not found (may already be off, or selector drifted)")

    if not verify:
        return clicked

    for attempt in range(VERIFY_RETRIES + 1):
        if _control_is_off(page, confirm_labels):
            logger.info(f"Verified {what} is off")
            return True
        if attempt == VERIFY_RETRIES:
            break
        logger.warning(f"{what} still on after attempt {attempt + 1}; trying again")
        _dismiss_popups(page)
        _try_click_by_role(page, "button", off_labels, 3000)

    logger.warning(f"Could not confirm {what} is off - joining anyway")
    return False


def _run_join_flow(
    page: Page,
    link: str,
    mute_mic: bool,
    mute_camera: bool,
    nav_timeout_s: int,
    control_timeout_s: int,
    verify_controls: bool = True,
) -> JoinResult:
    """The on-page steps shared by both launch modes: navigate, dismiss
    popups, mute mic/camera, confirm they took, click Join."""
    logger.info(f"Navigating to {link}")
    page.goto(link, wait_until="domcontentloaded", timeout=nav_timeout_s * 1000)

    page.wait_for_load_state("networkidle", timeout=nav_timeout_s * 1000)
    _dismiss_popups(page)

    if mute_mic:
        _turn_off_control(page, "Microphone", MIC_OFF_LABELS, MIC_CONFIRM_LABELS,
                          control_timeout_s, verify_controls)

    if mute_camera:
        _turn_off_control(page, "Camera", CAM_OFF_LABELS, CAM_CONFIRM_LABELS,
                          control_timeout_s, verify_controls)

    _dismiss_popups(page)

    # Last look before joining: dismissing a popup can re-enable a control,
    # so anything that drifted back on gets one more correction here.
    if verify_controls:
        if mute_mic and not _control_is_off(page, MIC_CONFIRM_LABELS, timeout_ms=800):
            logger.warning("Microphone came back on before joining; correcting")
            _turn_off_control(page, "Microphone", MIC_OFF_LABELS, MIC_CONFIRM_LABELS,
                              control_timeout_s, verify_controls)
        if mute_camera and not _control_is_off(page, CAM_CONFIRM_LABELS, timeout_ms=800):
            logger.warning("Camera came back on before joining; correcting")
            _turn_off_control(page, "Camera", CAM_OFF_LABELS, CAM_CONFIRM_LABELS,
                              control_timeout_s, verify_controls)

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
    browser_name: str = browsers.DEFAULT,
    verify_controls: bool = True,
) -> JoinResult:
    browser_name = browsers.normalize(browser_name)
    label = browsers.short_name(browser_name)
    try:
        with sync_playwright() as p:
            if use_running_chrome:
                # CDP is the same protocol on every Chromium browser, so this
                # branch is untouched apart from what it calls the browser.
                logger.info(f"Attaching to already-running {label} on port {cdp_port}")
                try:
                    browser = p.chromium.connect_over_cdp(f"http://localhost:{cdp_port}")
                except Exception as e:
                    logger.error(f"Could not attach to {label} on port {cdp_port}: {e}")
                    return JoinResult(
                        success=False,
                        message=(
                            f"Could not connect to {label} on port {cdp_port}. "
                            f"Make sure {label} was started with the debug launcher "
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
                return _run_join_flow(page, link, mute_mic, mute_camera, nav_timeout_s,
                                      control_timeout_s, verify_controls)

            # --- Launch modes (isolated profile or a real profile folder) ---
            resolved_dir = user_data_dir or str(paths.profile_dir_for(browser_name))
            launch_args = ["--disable-notifications"]
            if profile_directory:
                if browsers.uses_single_profile_dir(browser_name):
                    # Opera stores the profile inside a user-data-dir, so the
                    # saved path splits into the dir Playwright takes and the
                    # profile name that goes on the command line.
                    resolved_dir, profile_name = browsers.split_profile_path(profile_directory)
                    if profile_name:
                        launch_args.append(f"--profile-directory={profile_name}")
                else:
                    launch_args.append(f"--profile-directory={profile_directory}")

            # Chrome and Edge have a Playwright channel; the rest are launched
            # by executable path. Everything after this point is identical.
            channel = browsers.playwright_channel(browser_name)
            launch_target: dict = {}
            if channel:
                launch_target["channel"] = channel
                how = f"channel '{channel}'"
            else:
                executable = browsers.find_executable(browser_name)
                if not executable:
                    logger.error(f"No {label} executable found in standard install locations")
                    return JoinResult(
                        success=False,
                        message=(
                            f"Could not find {label} in its standard install locations. "
                            f"Install {label}, or use a different browser for this connection."
                        ),
                    )
                launch_target["executable_path"] = executable
                how = f"executable '{executable}'"

            logger.info(
                f"Launching {label} ({how}) with user_data_dir='{resolved_dir}' "
                f"profile_directory='{profile_directory or '(default)'}'"
            )

            context: BrowserContext = p.chromium.launch_persistent_context(
                user_data_dir=resolved_dir,
                headless=headless,
                permissions=["camera", "microphone"],
                args=launch_args,
                **launch_target,
            )
            page = context.new_page()
            page.set_default_timeout(control_timeout_s * 1000)

            # Opera opens its own startup page (GX Corner). Closing that one
            # blocks for minutes and then tears the whole context down, taking
            # the meeting tab with it - so those browsers keep their tabs.
            if not browsers.keeps_startup_pages(browser_name):
                for other_page in list(context.pages):
                    if other_page is not page:
                        try:
                            other_page.close()
                        except Exception:  # noqa: BLE001 - best-effort cleanup only
                            pass
            try:
                page.bring_to_front()
            except Exception as e:  # noqa: BLE001 - focus is cosmetic, never fatal
                logger.warning(f"Could not bring the meeting page to the front: {e}")

            return _run_join_flow(page, link, mute_mic, mute_camera, nav_timeout_s,
                                  control_timeout_s, verify_controls)

    except PWTimeoutError as e:
        logger.error(f"Timeout joining meeting: {e}")
        return JoinResult(success=False, message=f"Timed out waiting for Meet to load: {e}")
    except Exception as e:  # noqa: BLE001 - surface any automation error to the scheduler
        logger.exception("Unexpected automation error")
        return JoinResult(success=False, message=f"Automation error: {e}")
