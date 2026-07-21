"""
Background scheduler.

Runs in its own thread, polling the store every POLL_INTERVAL seconds.
When a meeting is close to starting, it fires a desktop notification;
when it's actually due, it hands off to the automation module *in a
separate thread* so a slow/hanging browser launch never freezes the poll
loop or the GUI.
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime

from storage import MeetingStore
from models import Meeting
import automation
import automation_uia
import notifier
import recurrence
import settings

logger = logging.getLogger("meet_automation")

POLL_INTERVAL_SECONDS = 15
NOTIFY_LEAD_SECONDS = 5 * 60  # notify 5 minutes before a meeting


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
            if m.chrome_connection:
                conn = settings.get_connection(m.chrome_connection)
                if conn and conn.get("backend") == "cdp":
                    message += f"\nMake sure Chrome is running via that connection's launcher ('{m.chrome_connection}')."
                elif conn and conn.get("backend") == "uia" and not conn.get("profile_directory"):
                    message += "\nMake sure Chrome is open before then."
            notifier.notify("🕒 Upcoming class", message)
            recurrence.mark_notified(m, now)
            self.store.update(m)
            self._report(f"Notified about '{m.title}'")

        # 2. Meetings due right now (skip any that already have a join
        # attempt in flight - without this guard, a join that takes longer
        # than one poll interval gets launched a second time, and the two
        # Chrome instances collide on the same profile lock).
        for m in self.store.due_meetings(now):
            with self._joining_lock:
                if m.id in self._joining_ids:
                    continue
                self._joining_ids.add(m.id)
            self._report(f"Joining '{m.title}'...")
            threading.Thread(target=self._join_meeting, args=(m,), daemon=True).start()

    def _join_meeting(self, m: Meeting) -> None:
        try:
            conn = settings.get_connection(m.chrome_connection) if m.chrome_connection else None
            if m.chrome_connection and not conn:
                logger.warning(
                    f"Connection '{m.chrome_connection}' no longer exists; "
                    f"falling back to the isolated profile for '{m.title}'"
                )

            if conn and conn.get("backend") == "uia":
                result = automation_uia.join_google_meet_uia(
                    link=m.link,
                    mute_mic=m.mute_mic,
                    mute_camera=m.mute_camera,
                    profile_directory=conn.get("profile_directory") or None,
                    title_hint=conn.get("title_hint") or None,
                )
            elif conn and conn.get("backend") == "cdp":
                result = automation.join_google_meet(
                    link=m.link,
                    mute_mic=m.mute_mic,
                    mute_camera=m.mute_camera,
                    use_running_chrome=True,
                    cdp_port=conn["port"],
                )
            else:
                result = automation.join_google_meet(
                    link=m.link,
                    mute_mic=m.mute_mic,
                    mute_camera=m.mute_camera,
                )

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
