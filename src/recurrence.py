"""
Recurrence rules for scheduled meetings.

Internal weekday numbering follows Python's datetime.weekday(): Monday=0 … Sunday=6.
The UI presents days in Apple Clock order (Sunday first) but all storage and
comparisons use the Python convention so scheduler logic stays simple.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta

# Python weekday() -> short display name
DAY_NAMES_SHORT = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")

# Apple Clock display order: Sunday first, then Mon … Sat
# Each entry is (python_weekday, single-letter label)
APPLE_DAY_ORDER: tuple[tuple[int, str], ...] = (
    (6, "S"), (0, "M"), (1, "T"), (2, "W"), (3, "T"), (4, "F"), (5, "S"),
)

WEEKDAYS = frozenset({0, 1, 2, 3, 4})
WEEKENDS = frozenset({5, 6})
ALL_DAYS = frozenset(range(7))

RECURRING_NONE = "none"
RECURRING_WEEKLY = "weekly"


def is_recurring(meeting) -> bool:
    return meeting.recurring == RECURRING_WEEKLY and bool(meeting.recurring_days)


def parse_days(value: str) -> frozenset[int]:
    """Parse a comma-separated list of weekday ints (Mon=0 … Sun=6)."""
    if not value or not value.strip():
        return frozenset()
    result: set[int] = set()
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        day = int(part)
        if 0 <= day <= 6:
            result.add(day)
    return frozenset(result)


def serialize_days(days: frozenset[int] | set[int]) -> str:
    if not days:
        return ""
    return ",".join(str(d) for d in sorted(days))


def format_repeat_label(days: frozenset[int]) -> str:
    """Human-readable repeat summary, e.g. 'Weekdays' or 'Every Mon, Wed, Fri'."""
    if not days:
        return "Repeat (no days selected)"
    if days == ALL_DAYS:
        return "Every day"
    if days == WEEKDAYS:
        return "Weekdays"
    if days == WEEKENDS:
        return "Weekends"
    names = [DAY_NAMES_SHORT[d] for d in sorted(days)]
    return "Every " + ", ".join(names)


def format_schedule_summary(meeting, now: datetime | None = None) -> str:
    """One-line schedule description for list views."""
    now = now or datetime.now()
    t = meeting.scheduled_time.strftime("%I:%M %p").lstrip("0")
    early = getattr(meeting, "join_early_minutes", 0) or 0
    suffix = f" (joins {early} min early)" if early > 0 else ""
    if is_recurring(meeting):
        days = parse_days(meeting.recurring_days)
        return f"{format_repeat_label(days)} at {t}{suffix}"
    d = meeting.scheduled_time.strftime("%b %d, %Y")
    return f"{d} at {t}{suffix}"


def _occurrence_datetime(meeting, on_date: date) -> datetime:
    """Combine a calendar date with the meeting's stored time-of-day.

    This is the *displayed* scheduled time - it never reflects
    join_early_minutes. Use _join_datetime() below for the time the
    automation should actually act.
    """
    t = meeting.scheduled_time.time()
    return datetime.combine(on_date, t)


def _join_datetime(meeting, on_date: date) -> datetime:
    """The actual moment automation should join, i.e. the occurrence time
    minus any configured early-join offset. The scheduled time shown in
    the UI is never changed - only this internal value shifts earlier.
    """
    early = getattr(meeting, "join_early_minutes", 0) or 0
    return _occurrence_datetime(meeting, on_date) - timedelta(minutes=early)


def is_active_on_date(meeting, on_date: date) -> bool:
    """Whether this meeting should fire on the given calendar date."""
    if is_recurring(meeting):
        days = parse_days(meeting.recurring_days)
        if on_date.weekday() not in days:
            return False
        return on_date >= meeting.scheduled_time.date()
    return on_date == meeting.scheduled_time.date()


def seconds_until_occurrence(meeting, now: datetime) -> float | None:
    """Seconds from *now* until the next occurrence, or None if not applicable today."""
    today = now.date()
    if not is_active_on_date(meeting, today):
        return None
    target = _occurrence_datetime(meeting, today)
    return (target - now).total_seconds()


def seconds_until_join(meeting, now: datetime) -> float | None:
    """Seconds from *now* until the automation should actually join, or
    None if not applicable today. Identical to seconds_until_occurrence()
    when join_early_minutes is 0 (the default), so existing behavior is
    unchanged unless a user opts into early joining.
    """
    today = now.date()
    if not is_active_on_date(meeting, today):
        return None
    target = _join_datetime(meeting, today)
    return (target - now).total_seconds()


def is_due(meeting, now: datetime, window_seconds: int = 30) -> bool:
    """True when the meeting should auto-join right now.

    The comparison is against the *join* time (scheduled_time minus
    join_early_minutes), not the displayed scheduled_time, so setting a
    "join early" offset makes automation fire earlier without changing
    what's shown as the meeting's scheduled time anywhere else.
    """
    if not meeting.auto_join:
        return False
    if is_recurring(meeting):
        delta = seconds_until_join(meeting, now)
        if delta is None:
            return False
        if meeting.last_joined_date == today_iso(now):
            return False
        return 0 <= delta <= window_seconds
    if meeting.joined:
        return False
    early = getattr(meeting, "join_early_minutes", 0) or 0
    join_time = meeting.scheduled_time - timedelta(minutes=early)
    delta = (now - join_time).total_seconds()
    return 0 <= delta <= window_seconds


def should_notify(meeting, now: datetime, lead_seconds: int) -> bool:
    """True when a pre-join notification should fire.

    Timed relative to the actual join time (which may be earlier than
    scheduled_time), so the heads-up always arrives before automation
    acts. With join_early_minutes at its default of 0 this is identical
    to the previous behavior.
    """
    if is_recurring(meeting):
        if meeting.last_notified_date == today_iso(now):
            return False
        delta = seconds_until_join(meeting, now)
        if delta is None:
            return False
        return 0 <= delta <= lead_seconds
    if meeting.notified or meeting.joined:
        return False
    early = getattr(meeting, "join_early_minutes", 0) or 0
    join_time = meeting.scheduled_time - timedelta(minutes=early)
    delta = (join_time - now).total_seconds()
    return 0 <= delta <= lead_seconds


def mark_notified(meeting, now: datetime) -> None:
    if is_recurring(meeting):
        meeting.last_notified_date = today_iso(now)
    else:
        meeting.notified = True


def mark_joined(meeting, now: datetime) -> None:
    if is_recurring(meeting):
        meeting.last_joined_date = today_iso(now)
        meeting.last_notified_date = today_iso(now)
    else:
        meeting.joined = True


def today_iso(now: datetime | None = None) -> str:
    return (now or datetime.now()).date().isoformat()


def migrate_legacy_recurring(recurring: str, scheduled_time: datetime) -> tuple[str, str]:
    """Convert pre–day-picker recurring values to weekly + days string."""
    if recurring == "daily":
        return RECURRING_WEEKLY, serialize_days(ALL_DAYS)
    if recurring == "weekly":
        return RECURRING_WEEKLY, serialize_days({scheduled_time.weekday()})
    if recurring == RECURRING_WEEKLY:
        return RECURRING_WEEKLY, ""
    return RECURRING_NONE, ""
