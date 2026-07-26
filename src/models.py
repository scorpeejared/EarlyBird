"""
Data model for a scheduled Google Meet class.
"""
from dataclasses import dataclass
from datetime import datetime

from recurrence import is_recurring, format_schedule_summary


@dataclass
class Meeting:
    id: int | None          # None until saved to DB (SQLite assigns the id)
    title: str              # e.g. "Calculus 101"
    link: str               # Google Meet URL
    scheduled_time: datetime
    auto_join: bool = True  # whether the app should join this one automatically
    mute_mic: bool = True
    mute_camera: bool = True
    recurring: str = "none"     # "none" or "weekly"
    recurring_days: str = ""    # comma-separated weekday ints (Mon=0 … Sun=6)
    join_early_minutes: int = 0  # automation joins this many minutes before scheduled_time
    notified: bool = False      # one-time: pre-join notification already fired
    joined: bool = False        # one-time: already auto-joined
    last_notified_date: str = ""  # recurring: ISO date of last pre-join notification
    last_joined_date: str = ""    # recurring: ISO date of last successful join
    notes: str = ""
    chrome_connection: str = ""  # name of a settings.py connection, or "" for the isolated profile

    def status_label(self) -> str:
        if is_recurring(self):
            return "Recurring"
        if self.joined:
            return "Joined"
        if not self.auto_join:
            return "Manual"
        return "Scheduled"

    def schedule_summary(self) -> str:
        return format_schedule_summary(self)
