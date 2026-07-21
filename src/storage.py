"""
SQLite-backed storage for meetings.

Using SQLite instead of a flat JSON file so the app can safely handle
concurrent reads (GUI thread) and writes (scheduler thread) without
worrying about corrupting a whole file on every save.
"""
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

from models import Meeting
import recurrence

DB_PATH = Path(__file__).parent.parent / "data" / "meetings.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meetings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    link TEXT NOT NULL,
    scheduled_time TEXT NOT NULL,   -- ISO 8601
    auto_join INTEGER NOT NULL DEFAULT 1,
    mute_mic INTEGER NOT NULL DEFAULT 1,
    mute_camera INTEGER NOT NULL DEFAULT 1,
    recurring TEXT NOT NULL DEFAULT 'none',
    recurring_days TEXT NOT NULL DEFAULT '',
    notified INTEGER NOT NULL DEFAULT 0,
    joined INTEGER NOT NULL DEFAULT 0,
    last_notified_date TEXT NOT NULL DEFAULT '',
    last_joined_date TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    chrome_connection TEXT NOT NULL DEFAULT '',
    join_early_minutes INTEGER NOT NULL DEFAULT 0
);
"""


class MeetingStore:
    """Thread-safe-enough wrapper around a single SQLite file.

    SQLite connections aren't shared across threads by default, so we
    open a fresh connection per call. For this app's write volume
    (a handful of rows, occasional writes) that's simpler and safer
    than managing a connection pool.
    """

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self._lock = threading.Lock()
        with self._connect() as conn:
            conn.execute(_SCHEMA)
            self._migrate(conn)

    def _migrate(self, conn: sqlite3.Connection) -> None:
        """Add columns introduced after the initial release."""
        existing_cols = {row["name"] for row in conn.execute("PRAGMA table_info(meetings)")}
        if "chrome_connection" not in existing_cols:
            conn.execute("ALTER TABLE meetings ADD COLUMN chrome_connection TEXT NOT NULL DEFAULT ''")
        if "recurring_days" not in existing_cols:
            conn.execute("ALTER TABLE meetings ADD COLUMN recurring_days TEXT NOT NULL DEFAULT ''")
        if "last_notified_date" not in existing_cols:
            conn.execute("ALTER TABLE meetings ADD COLUMN last_notified_date TEXT NOT NULL DEFAULT ''")
        if "last_joined_date" not in existing_cols:
            conn.execute("ALTER TABLE meetings ADD COLUMN last_joined_date TEXT NOT NULL DEFAULT ''")
        if "join_early_minutes" not in existing_cols:
            conn.execute("ALTER TABLE meetings ADD COLUMN join_early_minutes INTEGER NOT NULL DEFAULT 0")

        # Convert legacy daily/weekly rows to the new day-of-week format.
        rows = conn.execute("SELECT id, recurring, scheduled_time, recurring_days FROM meetings").fetchall()
        for row in rows:
            if row["recurring"] in ("daily", "weekly") or (
                row["recurring"] == recurrence.RECURRING_WEEKLY and not row["recurring_days"]
            ):
                scheduled = datetime.fromisoformat(row["scheduled_time"])
                new_recurring, new_days = recurrence.migrate_legacy_recurring(row["recurring"], scheduled)
                conn.execute(
                    "UPDATE meetings SET recurring=?, recurring_days=? WHERE id=?",
                    (new_recurring, new_days, row["id"]),
                )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    # ---------- CRUD ----------

    def add(self, m: Meeting) -> int:
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                """INSERT INTO meetings
                   (title, link, scheduled_time, auto_join, mute_mic, mute_camera,
                    recurring, recurring_days, notified, joined,
                    last_notified_date, last_joined_date, notes, chrome_connection,
                    join_early_minutes)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    m.title, m.link, m.scheduled_time.isoformat(),
                    int(m.auto_join), int(m.mute_mic), int(m.mute_camera),
                    m.recurring, m.recurring_days,
                    int(m.notified), int(m.joined),
                    m.last_notified_date, m.last_joined_date,
                    m.notes, m.chrome_connection,
                    int(m.join_early_minutes or 0),
                ),
            )
            return cur.lastrowid

    def update(self, m: Meeting) -> None:
        if m.id is None:
            raise ValueError("Cannot update a meeting without an id")
        with self._lock, self._connect() as conn:
            conn.execute(
                """UPDATE meetings SET title=?, link=?, scheduled_time=?, auto_join=?,
                   mute_mic=?, mute_camera=?, recurring=?, recurring_days=?,
                   notified=?, joined=?, last_notified_date=?, last_joined_date=?,
                   notes=?, chrome_connection=?, join_early_minutes=?
                   WHERE id=?""",
                (
                    m.title, m.link, m.scheduled_time.isoformat(),
                    int(m.auto_join), int(m.mute_mic), int(m.mute_camera),
                    m.recurring, m.recurring_days,
                    int(m.notified), int(m.joined),
                    m.last_notified_date, m.last_joined_date,
                    m.notes, m.chrome_connection,
                    int(m.join_early_minutes or 0), m.id,
                ),
            )

    def delete(self, meeting_id: int) -> None:
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM meetings WHERE id=?", (meeting_id,))

    def get(self, meeting_id: int) -> Optional[Meeting]:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM meetings WHERE id=?", (meeting_id,)).fetchone()
            return self._row_to_meeting(row) if row else None

    def all(self) -> list[Meeting]:
        with self._lock, self._connect() as conn:
            rows = conn.execute("SELECT * FROM meetings ORDER BY scheduled_time ASC").fetchall()
            return [self._row_to_meeting(r) for r in rows]

    def due_meetings(self, now: datetime, window_seconds: int = 30) -> list[Meeting]:
        """Meetings that should auto-join right now."""
        return [m for m in self.all() if recurrence.is_due(m, now, window_seconds)]

    def upcoming_for_notification(self, now: datetime, lead_seconds: int) -> list[Meeting]:
        """Meetings that should receive a pre-join notification."""
        return [m for m in self.all() if recurrence.should_notify(m, now, lead_seconds)]

    @staticmethod
    def _row_to_meeting(row: sqlite3.Row) -> Meeting:
        keys = row.keys()
        return Meeting(
            id=row["id"],
            title=row["title"],
            link=row["link"],
            scheduled_time=datetime.fromisoformat(row["scheduled_time"]),
            auto_join=bool(row["auto_join"]),
            mute_mic=bool(row["mute_mic"]),
            mute_camera=bool(row["mute_camera"]),
            recurring=row["recurring"],
            recurring_days=row["recurring_days"] if "recurring_days" in keys else "",
            notified=bool(row["notified"]),
            joined=bool(row["joined"]),
            last_notified_date=row["last_notified_date"] if "last_notified_date" in keys else "",
            last_joined_date=row["last_joined_date"] if "last_joined_date" in keys else "",
            notes=row["notes"],
            chrome_connection=row["chrome_connection"],
            join_early_minutes=row["join_early_minutes"] if "join_early_minutes" in keys else 0,
        )
