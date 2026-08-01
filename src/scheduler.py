"""
Background scheduler.

Runs in its own thread, polling the store every POLL_INTERVAL seconds.
When a meeting is close to starting, it fires a desktop notification;
when it's actually due, it hands off to the automation module *in a
separate thread* so a slow/hanging browser launch never freezes the poll
loop or the GUI.
"""
from __future__ import annotations

import threading
from datetime import datetime

from . import automation, automation_uia, browsers, notifier, recurrence, settings
from .logging_setup import get_logger
from .models import JoinResult, Meeting
from .storage import MeetingStore

logger = get_logger()

POLL_INTERVAL_SECONDS = 15
NOTIFY_LEAD_SECONDS = 5 * 60  # notify 5 minutes before a meeting


def perform_join(m: Meeting) -> JoinResult:
    """Run one join for this meeting through whichever backend it's set up for.

    Deliberately free of bookkeeping - no notifications, no marking the
    meeting joined - so the "Test run" button in the class dialog can reuse
    the real join path without touching saved state. The scheduler adds the
    bookkeeping around it.
    """
    conn = settings.get_connection(m.browser_connection) if m.browser_connection else None
    if m.browser_connection and not conn:
        logger.warning(
            f"Connection '{m.browser_connection}' no longer exists; "
            f"falling back to the isolated profile for '{m.title}'"
        )

    # The connection decides the browser; with no connection it's the
    # meeting's own field, which is "chrome" for the isolated profile.
    browser = browsers.resolve(m.browser, conn)

    if conn and conn.get("backend") == "uia":
        return automation_uia.join_google_meet_uia(
            link=m.link,
            mute_mic=m.mute_mic,
            mute_camera=m.mute_camera,
            profile_directory=conn.get("profile_directory") or None,
            title_hint=conn.get("title_hint") or None,
            browser=browser,
        )
    if conn and conn.get("backend") == "cdp":
        return automation.join_google_meet(
            link=m.link,
            mute_mic=m.mute_mic,
            mute_camera=m.mute_camera,
            use_running_chrome=True,
            cdp_port=conn["port"],
            browser_name=browser,
        )
    return automation.join_google_meet(
        link=m.link,
        mute_mic=m.mute_mic,
        mute_camera=m.mute_camera,
        browser_name=browser,
    )


class SchedulerService:
    def __init__(self, store: MeetingStore, on_status_change=None):
        self.store = store
        self.on_status_change = on_status_change
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._joining_lock = threading.Lock()
        self._joining_ids: set[int] = set()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        logger.info("Scheduler started")

    def stop(self) -> None:
        self._stop_event.set()

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._poll_once()
            except Exception:
                logger.exception("Error during scheduler poll")
            self._stop_event.wait(POLL_INTERVAL_SECONDS)

    def _poll_once(self) -> None:
        now = datetime.now()

        # 1. Pre-join notifications
        for m in self.store.upcoming_for_notification(now, NOTIFY_LEAD_SECONDS):
            message = f"{m.title}\n{m.scheduled_time.strftime('%I:%M %p').lstrip('0')}"
            if m.browser_connection:
                conn = settings.get_connection(m.browser_connection)
                browser_name = browsers.short_name(browsers.resolve(m.browser, conn))
                if conn and conn.get("backend") == "cdp":
                    message += f"\nMake sure {browser_name} is running via that connection's launcher ('{m.browser_connection}')."
                elif conn and conn.get("backend") == "uia" and not conn.get("profile_directory"):
                    message += f"\nMake sure {browser_name} is open before then."
            notifier.notify("🕒 Upcoming class", message)
            recurrence.mark_notified(m, now)
            self.store.update(m)
            self._report(f"Notified about '{m.title}'")

        # 2. Meetings due right now. Skip any join already in flight: one
        # that outlasts a poll interval would otherwise be launched twice,
        # and the two Chrome instances collide on the same profile lock.
        for m in self.store.due_meetings(now):
            with self._joining_lock:
                if m.id in self._joining_ids:
                    continue
                self._joining_ids.add(m.id)
            self._report(f"Joining '{m.title}'...")
            threading.Thread(target=self._join_meeting, args=(m,), daemon=True).start()

    def _join_meeting(self, m: Meeting) -> None:
        try:
            result = perform_join(m)

            if result.success:
                recurrence.mark_joined(m, datetime.now())
                self.store.update(m)
                notifier.notify(
                    "✅ Successfully joined",
                    f"{m.title}\n{m.scheduled_time.strftime('%I:%M %p').lstrip('0')}",
                )
                self._report(f"Joined '{m.title}'")
            else:
                notifier.notify("⚠️ Join failed", f"{m.title}\n{result.message}")
                self._report(f"Failed to join '{m.title}': {result.message}")
        finally:
            with self._joining_lock:
                self._joining_ids.discard(m.id)

    def _report(self, message: str) -> None:
        logger.info(message)
        if self.on_status_change:
            self.on_status_change(message)
