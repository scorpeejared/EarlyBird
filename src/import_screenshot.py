"""
Draft meetings extracted from a screenshot of a class schedule.

Everything here is a *draft*: a ParsedRow is what the parser thinks it saw,
not a Meeting. Nothing reaches the database until the user has reviewed the
rows and confirmed them, at which point to_meeting() turns each kept row into
a real Meeting for MeetingStore.add().

Scope is deliberately narrow - title, day(s)/date, time, link. Assignment
deadlines, grading policy and office hours are not meetings and are not
extracted.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, time

from . import ai_provider, browsers, recurrence, secret_store, settings
from .logging_setup import get_logger
from .models import Meeting

logger = get_logger()

# Parser-reported certainty per field. Anything other than "high" gets
# surfaced in the review screen so the user knows where to look.
HIGH = "high"
MEDIUM = "medium"
LOW = "low"

# The parser may only report warnings from this set - a closed vocabulary
# keeps the review screen's badges predictable and translatable, and stops a
# model from inventing its own warning strings.
WARNING_LABELS = {
    "ampm_ambiguous": "AM/PM unclear",
    "no_year_on_date": "Year missing",
    "no_link_found": "No link found",
    "no_time_found": "No time found",
    "title_unclear": "Title unclear",
    "days_unclear": "Days unclear",
    "text_partly_illegible": "Hard to read",
}

RECURRENCE_WEEKLY = "weekly"
RECURRENCE_ONCE = "once"

# Model-facing day codes, in Python weekday order (Mon=0 ... Sun=6).
_DAY_CODES = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
_DAY_TO_WEEKDAY = {code: i for i, code in enumerate(_DAY_CODES)}

_TIME_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")
_CONFIDENCES = (HIGH, MEDIUM, LOW)

# Anything longer is a paragraph the parser mistook for a course name.
_MAX_TITLE_CHARS = 120

SYSTEM_PROMPT = """You extract class-meeting schedules from screenshots of \
syllabi and timetables.

Scope: meeting title, meeting day(s) or date, start time, and meeting link. \
Nothing else. Ignore assignment due dates, grading policy, office hours, \
instructor contact info, exam dates, and any other syllabus content - those are \
not meetings the user wants scheduled. A full syllabus page that contains one \
schedule table is normal: extract the table and ignore everything around it.

Rules:
- Report only what the image actually shows. Never invent a link, a year, or a \
time that is not visible.
- "MWF 10:00" is ONE weekly recurring row with three days, not three rows.
- A bare date like "10/14" with no repeat pattern is a one-time meeting.
- If a time is written without AM/PM, still report your best reading, but set \
time_confidence to "low" and add an ampm_ambiguous warning.
- If a date has no year, report the month and day with your best-guess year and \
set date_confidence to "low".
- If the image contains no class-schedule content at all, set found_schedule to \
false, explain why in no_schedule_reason, and return an empty rows array.

Respond only with JSON matching the schema. No preamble."""

USER_PROMPT = "Extract every class meeting from this schedule image."

# Constrained to the JSON Schema subset Gemini documents as supported: types
# (including ["x","null"] for nullable), enum, description and required.
RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "found_schedule": {
            "type": "boolean",
            "description": "True only if this image actually contains a class/meeting schedule.",
        },
        "no_schedule_reason": {
            "type": ["string", "null"],
            "description": "If found_schedule is false, one short sentence on what the image showed instead.",
        },
        "rows": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Course or meeting name as written."},
                    "recurrence": {
                        "type": "string",
                        "enum": [RECURRENCE_WEEKLY, RECURRENCE_ONCE],
                        "description": "'weekly' if the row names days of the week; 'once' if it names a single date.",
                    },
                    "days": {
                        "type": "array",
                        "items": {"type": "string", "enum": list(_DAY_CODES)},
                        "description": "Weekdays for a weekly row. Empty for a one-time row.",
                    },
                    "date": {
                        "type": ["string", "null"],
                        "description": "ISO YYYY-MM-DD for a one-time row, else null.",
                    },
                    "start_time": {
                        "type": ["string", "null"],
                        "description": "24-hour HH:MM. Null if no time is shown.",
                    },
                    "link": {
                        "type": ["string", "null"],
                        "description": "Meeting URL if one is visible in the image, else null. Never guess one.",
                    },
                    "title_confidence": {"type": "string", "enum": list(_CONFIDENCES)},
                    "day_confidence": {"type": "string", "enum": list(_CONFIDENCES)},
                    "time_confidence": {"type": "string", "enum": list(_CONFIDENCES)},
                    "warnings": {
                        "type": "array",
                        "items": {"type": "string", "enum": list(WARNING_LABELS)},
                    },
                },
                "required": [
                    "title", "recurrence", "days", "date", "start_time", "link",
                    "title_confidence", "day_confidence", "time_confidence", "warnings",
                ],
            },
        },
    },
    "required": ["found_schedule", "no_schedule_reason", "rows"],
}


class ParseError(Exception):
    """Raised when a screenshot can't be turned into draft rows at all.

    Carries a message written for the user, not a stack trace - "couldn't
    find a schedule table in this image" rather than a JSON decode error.
    """


@dataclass
class ParsedRow:
    """One candidate meeting, straight off the parser and still editable."""

    title: str = ""
    recurrence: str = RECURRENCE_ONCE
    days: frozenset[int] = frozenset()      # Python weekdays, Mon=0 ... Sun=6
    on_date: date | None = None             # one-time rows only
    start_time: time | None = None
    link: str = ""
    title_confidence: str = HIGH
    day_confidence: str = HIGH
    time_confidence: str = HIGH
    warnings: tuple[str, ...] = ()

    def is_uncertain(self) -> bool:
        """True when anything about this row deserves a second look."""
        return bool(self.warnings) or any(
            c != HIGH for c in
            (self.title_confidence, self.day_confidence, self.time_confidence)
        )

    def warning_labels(self) -> list[str]:
        """Human-readable badges, unknown codes dropped rather than shown raw."""
        return [WARNING_LABELS[w] for w in self.warnings if w in WARNING_LABELS]


@dataclass
class ParseResult:
    """Outcome of parsing one image."""

    found_schedule: bool
    rows: list[ParsedRow] = field(default_factory=list)
    reason: str = ""  # why nothing was found, when found_schedule is False
    dropped: int = 0  # rows the sanitiser rejected as unreadable


def to_meeting(row: ParsedRow, start_from: date | None = None) -> Meeting:
    """Turn a reviewed draft row into a Meeting for MeetingStore.add().

    A row with no link is saved as a manual (non-auto-join) entry rather than
    being dropped - a syllabus that lists times but no links is the common
    case, and those rows are still worth having on the schedule.
    """
    today = start_from or date.today()
    at = row.start_time or time(0, 0)

    if row.recurrence == RECURRENCE_WEEKLY and row.days:
        # Recurring meetings fire on any matching weekday from their start
        # date onward, so anchoring to today makes the next occurrence the
        # first one - see recurrence.is_active_on_date().
        scheduled = datetime.combine(today, at)
        recurring = recurrence.RECURRING_WEEKLY
        recurring_days = recurrence.serialize_days(row.days)
    else:
        scheduled = datetime.combine(row.on_date or today, at)
        recurring = recurrence.RECURRING_NONE
        recurring_days = ""

    return Meeting(
        id=None,
        title=row.title.strip(),
        link=row.link.strip(),
        scheduled_time=scheduled,
        # No link means nothing to join, so the meeting is a reminder only.
        auto_join=bool(row.link.strip()),
        recurring=recurring,
        recurring_days=recurring_days,
        browser_connection="",          # the app's own isolated profile
        browser=browsers.DEFAULT,
    )


# ---------- turning model JSON into draft rows ----------
#
# Nothing below trusts the model. Every field is re-checked against the app's
# own rules, and a row that can't be read is dropped and counted rather than
# passed through half-broken - the caller reports the count so a dropped row
# is never silent.


def _clean_text(value, limit: int) -> str:
    return value.strip()[:limit] if isinstance(value, str) else ""


def _clean_confidence(value) -> str:
    """Unknown certainty is treated as low, never as high."""
    return value if value in _CONFIDENCES else LOW


def _clean_days(value) -> frozenset[int]:
    if not isinstance(value, list):
        return frozenset()
    return frozenset(
        _DAY_TO_WEEKDAY[d.strip().lower()] for d in value
        if isinstance(d, str) and d.strip().lower() in _DAY_TO_WEEKDAY
    )


def _clean_time(value) -> time | None:
    if not isinstance(value, str):
        return None
    match = _TIME_RE.match(value.strip())
    if not match:
        return None
    return time(int(match.group(1)), int(match.group(2)))


def _clean_date(value) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        return None


def _clean_link(value) -> str:
    """Keep any http(s) URL; the review screen decides if it's a usable Meet link.

    Deliberately not validated here: showing the user the URL the parser
    actually saw - and letting the Add/Edit link check reject it on confirm -
    beats silently discarding it and leaving them wondering.
    """
    text = _clean_text(value, 500)
    return text if text.lower().startswith(("http://", "https://")) else ""


def _clean_warnings(value) -> list[str]:
    if not isinstance(value, list):
        return []
    seen: list[str] = []
    for w in value:
        if isinstance(w, str) and w in WARNING_LABELS and w not in seen:
            seen.append(w)
    return seen


def _coerce_row(raw) -> ParsedRow | None:
    """One model row -> one ParsedRow, or None if it can't be salvaged."""
    if not isinstance(raw, dict):
        return None

    title = _clean_text(raw.get("title"), _MAX_TITLE_CHARS)
    if not title:
        return None  # a meeting with no name is not reviewable

    days = _clean_days(raw.get("days"))
    start_time = _clean_time(raw.get("start_time"))
    on_date = _clean_date(raw.get("date"))
    link = _clean_link(raw.get("link"))

    # Trust the shape of the data over the model's own label, and never guess
    # a repeat pattern: a row with no usable weekdays becomes a one-time
    # meeting even if the model called it weekly.
    recurrence_kind = RECURRENCE_WEEKLY if days else RECURRENCE_ONCE

    warnings = _clean_warnings(raw.get("warnings"))
    # Re-derive the warnings the UI depends on, so a row is flagged correctly
    # even when the model forgets to flag it.
    if not link and "no_link_found" not in warnings:
        warnings.append("no_link_found")
    if start_time is None and "no_time_found" not in warnings:
        warnings.append("no_time_found")
    if raw.get("recurrence") == RECURRENCE_WEEKLY and not days:
        if "days_unclear" not in warnings:
            warnings.append("days_unclear")

    return ParsedRow(
        title=title,
        recurrence=recurrence_kind,
        days=days,
        on_date=on_date,
        start_time=start_time,
        link=link,
        title_confidence=_clean_confidence(raw.get("title_confidence")),
        day_confidence=_clean_confidence(raw.get("day_confidence")),
        time_confidence=_clean_confidence(raw.get("time_confidence")),
        warnings=tuple(warnings),
    )


def coerce_result(payload) -> ParseResult:
    """Validate a decoded model response into a ParseResult.

    Separate from the network call so it can be tested against hostile input
    without an API key.
    """
    if not isinstance(payload, dict):
        raise ParseError("The parser sent back something unreadable. Please try again.")

    if not payload.get("found_schedule"):
        reason = _clean_text(payload.get("no_schedule_reason"), 300)
        return ParseResult(found_schedule=False, reason=reason)

    raw_rows = payload.get("rows")
    if not isinstance(raw_rows, list):
        raw_rows = []

    rows: list[ParsedRow] = []
    dropped = 0
    for raw in raw_rows:
        row = _coerce_row(raw)
        if row is None:
            dropped += 1
        else:
            rows.append(row)

    if not rows:
        return ParseResult(
            found_schedule=False,
            reason="Couldn't read any class times from this image.",
            dropped=dropped,
        )
    return ParseResult(found_schedule=True, rows=rows, dropped=dropped)


# ---------- the network call ----------


def parse_screenshot(image_bytes: bytes, mime_type: str = "image/png") -> ParseResult:
    """Send one image to the user's chosen AI and return draft rows.

    Blocks on the network - call it from a worker thread, never the GUI one.
    Raises ParseError with a message written for the user.
    """
    if not image_bytes:
        raise ParseError("That image was empty.")

    config = settings.get_ai_config()
    provider_id = config["provider"]

    try:
        payload = ai_provider.generate_json(
            provider_id=provider_id,
            model=config["model"],
            base_url=config["base_url"],
            api_key=secret_store.get_key(provider_id),
            system_prompt=SYSTEM_PROMPT,
            user_prompt=USER_PROMPT,
            image_bytes=image_bytes,
            mime_type=mime_type,
            schema=RESPONSE_SCHEMA,
        )
    except ai_provider.ProviderError as e:
        # Already phrased for the user by the provider layer.
        raise ParseError(str(e)) from e

    return coerce_result(payload)


def mock_result() -> ParseResult:
    """Stand-in parser output used to build and demo the review screen.

    Covers every state the review UI has to render: a clean row, an
    ambiguous time, a missing link, a missing time, a dateless one-off and a
    barely-legible title. Replaced by the real parser in the next phase.
    """
    return ParseResult(
        found_schedule=True,
        rows=[
            ParsedRow(
                title="Calculus 101",
                recurrence=RECURRENCE_WEEKLY,
                days=frozenset({0, 2, 4}),
                start_time=time(10, 0),
                link="https://meet.google.com/abc-defg-hij",
            ),
            ParsedRow(
                title="Organic Chemistry Lab",
                recurrence=RECURRENCE_WEEKLY,
                days=frozenset({1, 3}),
                start_time=time(14, 0),
                time_confidence=LOW,
                warnings=("ampm_ambiguous", "no_link_found"),
            ),
            ParsedRow(
                title="Midterm Review Session",
                recurrence=RECURRENCE_ONCE,
                on_date=date(date.today().year, 10, 14),
                start_time=time(16, 30),
                warnings=("no_year_on_date", "no_link_found"),
            ),
            ParsedRow(
                title="Intro to Psychology",
                recurrence=RECURRENCE_WEEKLY,
                days=frozenset({4}),
                start_time=None,
                title_confidence=LOW,
                day_confidence=MEDIUM,
                warnings=("no_time_found", "text_partly_illegible"),
            ),
            ParsedRow(
                title="Linear Algebra Seminar",
                recurrence=RECURRENCE_WEEKLY,
                days=frozenset({2}),
                start_time=time(9, 0),
                link="https://meet.google.com/xyz-1234-abc",
            ),
        ],
    )
