"""A single scheduled-class row shown in the class list."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout

from qfluentwidgets import CardWidget, CaptionLabel, FluentIcon, StrongBodyLabel, TransparentToolButton, isDarkTheme

from src.models import Meeting

from .. import theme
from .badge import make_badge


def _status_badge_spec(m: Meeting):
    dark = isDarkTheme()
    label = m.status_label()
    if label == "Recurring":
        return "🔁 Recurring", theme.ACCENT, (theme.ACCENT_BG_DARK if dark else theme.ACCENT_BG)
    if label == "Joined":
        return "🔵 Joined", theme.ACCENT, (theme.ACCENT_BG_DARK if dark else theme.ACCENT_BG)
    if label == "Manual":
        return "⚪ Manual", theme.NEUTRAL, (theme.NEUTRAL_BG_DARK if dark else theme.NEUTRAL_BG)
    return "🟢 Scheduled", theme.SUCCESS, (theme.SUCCESS_BG_DARK if dark else theme.SUCCESS_BG)


class MeetingCard(CardWidget):
    """Clickable card showing one class, with edit/notify/delete actions."""

    selected = Signal(int)
    editRequested = Signal(int)
    deleteRequested = Signal(int)
    toggleRequested = Signal(int)

    def __init__(self, meeting: Meeting, is_selected: bool = False, parent=None):
        super().__init__(parent)
        self.meeting_id = meeting.id
        self.setBorderRadius(theme.CARD_RADIUS)
        self.clicked.connect(lambda: self.selected.emit(self.meeting_id))
        self._set_selected(is_selected)

        root = QHBoxLayout(self)
        root.setContentsMargins(18, 14, 14, 14)
        root.setSpacing(12)

        left = QVBoxLayout()
        left.setSpacing(4)

        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        title_label = StrongBodyLabel(meeting.title, self)
        title_row.addWidget(title_label)
        text, fg, bg = _status_badge_spec(meeting)
        title_row.addWidget(make_badge(text, fg, bg, self))
        title_row.addStretch(1)
        left.addLayout(title_row)

        conn_label = meeting.chrome_connection or "Isolated profile"
        auto_label = "Auto-join on" if meeting.auto_join else "Manual only"
        meta = f"🕒 {meeting.schedule_summary()}    🔌 {conn_label}    {auto_label}"
        meta_label = CaptionLabel(meta, self)
        meta_label.setTextColor("#6B7280", "#9CA3AF")
        left.addWidget(meta_label)

        link_label = CaptionLabel(meeting.link, self)
        link_label.setTextColor("#6B7280", "#9CA3AF")
        left.addWidget(link_label)

        root.addLayout(left, 1)

        actions = QHBoxLayout()
        actions.setSpacing(2)
        edit_btn = TransparentToolButton(FluentIcon.EDIT, self)
        edit_btn.setToolTip("Edit class")
        edit_btn.clicked.connect(lambda: self.editRequested.emit(self.meeting_id))
        toggle_btn = TransparentToolButton(FluentIcon.RINGER, self)
        toggle_btn.setToolTip("Toggle auto-join")
        toggle_btn.clicked.connect(lambda: self.toggleRequested.emit(self.meeting_id))
        delete_btn = TransparentToolButton(FluentIcon.DELETE, self)
        delete_btn.setToolTip("Delete class")
        delete_btn.clicked.connect(lambda: self.deleteRequested.emit(self.meeting_id))
        for b in (edit_btn, toggle_btn, delete_btn):
            actions.addWidget(b)
        root.addLayout(actions)

    def _set_selected(self, is_selected: bool) -> None:
        if is_selected:
            self.setStyleSheet(f"MeetingCard {{ border: 2px solid {theme.ACCENT}; }}")
        else:
            self.setStyleSheet("")
