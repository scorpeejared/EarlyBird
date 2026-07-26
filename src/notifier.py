"""
Cross-platform desktop notifications.

Uses plyer (works on Windows/macOS/Linux) so we're not tied to a single OS.
"""
import logging

logger = logging.getLogger("meet_automation")


def notify(title: str, message: str, timeout: int = 10) -> None:
    try:
        from plyer import notification
        notification.notify(title=title, message=message, timeout=timeout, app_name="EarlyBird 🐦")
    except Exception as e:  # noqa: BLE001 - never let a notification failure break scheduling
        logger.warning(f"Notification failed ({e}); falling back to console")
        print(f"[NOTIFICATION] {title}: {message}")
