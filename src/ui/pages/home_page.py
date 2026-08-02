"""Home page: dashboard summary + the scheduled-class list."""
from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QVBoxLayout, QWidget

from qfluentwidgets import (
    CaptionLabel,
    FluentIcon,
    PrimaryPushButton,
    PushButton,
    ScrollArea,
    StrongBodyLabel,
    SubtitleLabel,
)

from ... import recurrence
from ...models import Meeting

from ..widgets.meeting_card import MeetingCard
from ..widgets.stat_card import StatCard
from .. import theme


class HomePage(QWidget):
    addClicked = Signal()
    importClicked = Signal()
    editClicked = Signal()
    deleteClicked = Signal()
    toggleClicked = Signal()
    meetingSelected = Signal(int)
    meetingEditRequested = Signal(int)
    meetingDeleteRequested = Signal(int)
    meetingToggleRequested = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("HomePage")

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 20)
        root.setSpacing(14)

        header = QVBoxLayout()
        header.setSpacing(2)
        header.addWidget(SubtitleLabel("Your classes", self))
        subtitle = CaptionLabel(
            "Automatic join · mic & camera off · runs quietly in the background", self
        )
        subtitle.setTextColor("#6B7280", "#9CA3AF")
        header.addWidget(subtitle)
        root.addLayout(header)

        self.stats_row = QHBoxLayout()
        self.stats_row.setSpacing(12)
        root.addLayout(self.stats_row)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        add_btn = PrimaryPushButton(FluentIcon.ADD, "Add class", self)
        add_btn.clicked.connect(self.addClicked)
        import_btn = PushButton(FluentIcon.PHOTO, "Import from screenshot", self)
        import_btn.setToolTip("Read a syllabus or timetable image and review the classes it finds")
        import_btn.clicked.connect(self.importClicked)
        edit_btn = PushButton(FluentIcon.EDIT, "Edit", self)
        edit_btn.clicked.connect(self.editClicked)
        delete_btn = PushButton(FluentIcon.DELETE, "Delete", self)
        delete_btn.clicked.connect(self.deleteClicked)
        toggle_btn = PushButton(FluentIcon.RINGER, "Toggle auto-join", self)
        toggle_btn.clicked.connect(self.toggleClicked)
        for b in (add_btn, import_btn, edit_btn, delete_btn, toggle_btn):
            toolbar.addWidget(b)
        toolbar.addStretch(1)
        root.addLayout(toolbar)

        self.scroll_area = ScrollArea(self)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.NoFrame)

        self.list_container = QWidget(self.scroll_area)
        self.list_layout = QVBoxLayout(self.list_container)
        self.list_layout.setContentsMargins(0, 0, 4, 0)
        self.list_layout.setSpacing(10)
        self.list_layout.addStretch(1)
        self.scroll_area.setWidget(self.list_container)
        # Must run after setWidget(): it only styles self.widget().
        self.scroll_area.enableTransparentBackground()
        root.addWidget(self.scroll_area, 1)

        self._selected_id: int | None = None
        self._watching_count = 0

    # ---------- public API ----------

    def set_meetings(self, meetings: list[Meeting], selected_id: int | None) -> None:
        self._selected_id = selected_id
        self._rebuild_stats(meetings)
        self._rebuild_list(meetings)

    def watching_count(self) -> int:
        return self._watching_count

    # ---------- internals ----------

    def _compute_stats(self, meetings: list[Meeting]):
        today = datetime.now().date()
        now = datetime.now()
        todays = [m for m in meetings if recurrence.is_active_on_date(m, today)]
        upcoming = [
            m for m in meetings
            if m.auto_join and (
                (recurrence.is_recurring(m) and recurrence.parse_days(m.recurring_days))
                or (not recurrence.is_recurring(m) and m.scheduled_time > now and not m.joined)
            )
        ]
        joined_today = [
            m for m in meetings
            if (recurrence.is_recurring(m) and m.last_joined_date == today.isoformat())
            or (not recurrence.is_recurring(m) and m.joined and m.scheduled_time.date() == today)
        ]
        watching = [m for m in meetings if m.auto_join and (recurrence.is_recurring(m) or not m.joined)]
        return len(todays), len(upcoming), len(joined_today), len(watching)

    def _rebuild_stats(self, meetings: list[Meeting]) -> None:
        while self.stats_row.count():
            item = self.stats_row.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        today_n, upcoming_n, joined_n, watching_n = self._compute_stats(meetings)
        self._watching_count = watching_n
        cards = [
            (FluentIcon.CALENDAR, today_n, "Today's Classes", theme.ACCENT),
            (FluentIcon.STOP_WATCH, upcoming_n, "Upcoming Classes", theme.WARNING),
            (FluentIcon.COMPLETED, joined_n, "Joined Today", theme.SUCCESS),
        ]
        for icon, value, label, accent in cards:
            self.stats_row.addWidget(StatCard(icon, value, label, accent, self), 1)

    def _rebuild_list(self, meetings: list[Meeting]) -> None:
        while self.list_layout.count():
            item = self.list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not meetings:
            self.list_layout.addWidget(self._build_empty_state())
            self.list_layout.addStretch(1)
            return

        for m in meetings:
            card = MeetingCard(m, is_selected=(m.id == self._selected_id), parent=self.list_container)
            card.selected.connect(self._on_card_selected)
            card.editRequested.connect(self.meetingEditRequested)
            card.deleteRequested.connect(self.meetingDeleteRequested)
            card.toggleRequested.connect(self.meetingToggleRequested)
            self.list_layout.addWidget(card)
        self.list_layout.addStretch(1)

    def _on_card_selected(self, meeting_id: int) -> None:
        self._selected_id = meeting_id
        self.meetingSelected.emit(meeting_id)

    def _build_empty_state(self) -> QWidget:
        wrap = QWidget(self.list_container)
        layout = QVBoxLayout(wrap)
        layout.setAlignment(Qt.AlignHCenter)
        layout.setContentsMargins(0, 60, 0, 60)
        layout.setSpacing(6)

        icon_label = StrongBodyLabel("🎓", wrap)
        icon_label.setAlignment(Qt.AlignHCenter)
        icon_label.setStyleSheet("font-size: 40px;")
        layout.addWidget(icon_label)

        heading = StrongBodyLabel("No scheduled classes yet.", wrap)
        heading.setAlignment(Qt.AlignHCenter)
        layout.addWidget(heading)

        hint = CaptionLabel(
            'Press "+ Add class" above, or import a timetable screenshot.', wrap
        )
        hint.setAlignment(Qt.AlignHCenter)
        hint.setTextColor("#6B7280", "#9CA3AF")
        layout.addWidget(hint)

        return wrap
