"""Review screen for meetings drafted from a schedule screenshot.

The parser's output is a draft, never a save. This dialog is the only path
from a parsed row to the database: every field stays editable, every row can
be excluded, and anything the parser was unsure about is badged so the user
knows where to look. Confirming builds Meetings and hands them back - the
caller writes them via MeetingStore.add().
"""
from __future__ import annotations

from datetime import date, time

from PySide6.QtCore import QDate, QTime, Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QVBoxLayout, QWidget

from qfluentwidgets import (
    CaptionLabel,
    CardWidget,
    CheckBox,
    ComboBox,
    DatePicker,
    InfoBar,
    InfoBarPosition,
    LineEdit,
    MessageBoxBase,
    ScrollArea,
    StrongBodyLabel,
    TimePicker,
    TransparentPushButton,
    isDarkTheme,
)

from ... import import_screenshot
from ...import_screenshot import ParsedRow, ParseResult
from ...models import Meeting

from .. import theme
from ..widgets.badge import make_badge
from ..widgets.day_picker import DayOfWeekPicker
from .meeting_dialog import looks_like_google_meet_link

# Same reason as MeetingDialog: MaskDialogBase sizes to the parent window, so
# a taller list is silently clipped rather than growing the dialog.
_CONTENT_MAX_HEIGHT = 420

_REPEAT_WEEKLY = "Repeats weekly"
_REPEAT_ONCE = "One-time"


class _RowEditor(CardWidget):
    """One draft meeting, fully editable, with a keep/skip checkbox."""

    def __init__(self, row: ParsedRow, parent=None):
        super().__init__(parent)
        self.setBorderRadius(theme.CARD_RADIUS)
        self._source = row

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(8)

        # --- title row: keep/skip, title, and what the parser was unsure of
        top = QHBoxLayout()
        top.setSpacing(10)
        self.include_box = CheckBox(self)
        # A row with no time at all would otherwise be saved at midnight, so
        # it starts unchecked: the user has to set a time and opt it back in.
        # Everything else defaults to included.
        self.include_box.setChecked(row.start_time is not None)
        top.addWidget(self.include_box)

        self.title_edit = LineEdit(self)
        self.title_edit.setText(row.title)
        self.title_edit.setPlaceholderText("Class name")
        # Keeps the field usable on rows carrying two or three badges.
        self.title_edit.setMinimumWidth(200)
        top.addWidget(self.title_edit, 1)

        for label in self._badge_labels(row):
            top.addWidget(make_badge(
                f"⚠ {label}", theme.WARNING,
                theme.WARNING_BG_DARK if isDarkTheme() else theme.WARNING_BG, self,
            ))
        root.addLayout(top)

        # --- schedule row: repeat mode, days or date, time
        schedule = QHBoxLayout()
        schedule.setSpacing(10)

        self.repeat_combo = ComboBox(self)
        self.repeat_combo.addItems([_REPEAT_WEEKLY, _REPEAT_ONCE])
        is_weekly = row.recurrence == import_screenshot.RECURRENCE_WEEKLY
        self.repeat_combo.setCurrentText(_REPEAT_WEEKLY if is_weekly else _REPEAT_ONCE)
        self.repeat_combo.currentTextChanged.connect(self._on_repeat_changed)
        self.repeat_combo.setFixedWidth(140)
        schedule.addWidget(self.repeat_combo)

        self.day_picker = DayOfWeekPicker(row.days, self, compact=True)
        schedule.addWidget(self.day_picker)

        self.date_picker = DatePicker(self)
        on_date = row.on_date or date.today()
        self.date_picker.setDate(QDate(on_date.year, on_date.month, on_date.day))
        schedule.addWidget(self.date_picker)

        self.time_picker = TimePicker(self)
        at = row.start_time or time(9, 0)
        self.time_picker.setTime(QTime(at.hour, at.minute))
        schedule.addWidget(self.time_picker)
        schedule.addStretch(1)
        root.addLayout(schedule)

        # --- link row
        link_row = QHBoxLayout()
        link_row.setSpacing(10)
        self.link_edit = LineEdit(self)
        self.link_edit.setText(row.link)
        self.link_edit.setPlaceholderText("https://meet.google.com/xxx-yyyy-zzz  (optional)")
        self.link_edit.textChanged.connect(self._update_join_hint)
        link_row.addWidget(self.link_edit, 1)

        self.join_hint = CaptionLabel("", self)
        link_row.addWidget(self.join_hint)
        root.addLayout(link_row)

        self.error_label = CaptionLabel("", self)
        self.error_label.setTextColor(theme.DANGER, theme.DANGER)
        self.error_label.setWordWrap(True)
        self.error_label.hide()
        root.addWidget(self.error_label)

        self._flagged = bool(self._badge_labels(row))
        self._on_repeat_changed(self.repeat_combo.currentText())
        self._update_join_hint()

    def was_flagged(self) -> bool:
        """True if the parser was unsure about anything in this row."""
        return self._flagged

    # ---------- display helpers ----------

    @staticmethod
    def _badge_labels(row: ParsedRow) -> list[str]:
        """Warning badges, plus a fallback badge per low-confidence field.

        A specific warning always wins: "AM/PM unclear" already tells the user
        to check the time, so a generic "Time unsure" next to it is noise.
        """
        labels = row.warning_labels()
        covered = {
            "title": {"title_unclear", "text_partly_illegible"},
            "day": {"days_unclear"},
            "time": {"ampm_ambiguous", "no_time_found"},
        }
        seen = set(row.warnings)
        for field_name, value, text in (
            ("title", row.title_confidence, "Title unsure"),
            ("day", row.day_confidence, "Days unsure"),
            ("time", row.time_confidence, "Time unsure"),
        ):
            if value != import_screenshot.HIGH and not (covered[field_name] & seen):
                labels.append(text)
        return labels

    def _on_repeat_changed(self, text: str) -> None:
        weekly = text == _REPEAT_WEEKLY
        self.day_picker.setVisible(weekly)
        self.date_picker.setVisible(not weekly)

    def _update_join_hint(self, *_args) -> None:
        """Say plainly what saving this row will do about auto-join."""
        if self.link_edit.text().strip():
            self.join_hint.setText("Auto-joins")
            self.join_hint.setTextColor(theme.SUCCESS, theme.SUCCESS)
        else:
            self.join_hint.setText("Saves as manual — no link")
            self.join_hint.setTextColor("#6B7280", "#9CA3AF")

    def set_error(self, message: str) -> None:
        self.error_label.setText(message)
        self.error_label.setVisible(bool(message))

    # ---------- read-back ----------

    def is_included(self) -> bool:
        return self.include_box.isChecked()

    def to_row(self) -> ParsedRow:
        """The row as it now stands on screen, edits included."""
        weekly = self.repeat_combo.currentText() == _REPEAT_WEEKLY
        qdate = self.date_picker.getDate()
        qtime = self.time_picker.getTime()
        return ParsedRow(
            title=self.title_edit.text().strip(),
            recurrence=(import_screenshot.RECURRENCE_WEEKLY if weekly
                        else import_screenshot.RECURRENCE_ONCE),
            days=self.day_picker.get_days() if weekly else frozenset(),
            on_date=None if weekly else date(qdate.year(), qdate.month(), qdate.day()),
            start_time=time(qtime.hour(), qtime.minute()),
            link=self.link_edit.text().strip(),
        )

    def validate(self) -> str:
        """Empty string when this row is safe to save, else why not."""
        row = self.to_row()
        if not row.title:
            return "Give this class a name, or untick it to skip."
        if row.recurrence == import_screenshot.RECURRENCE_WEEKLY and not row.days:
            return "Pick at least one day, or switch this to a one-time class."
        if row.link:
            # Same check the Add/Edit dialog runs - a bad link is worth
            # blocking, but a missing one just means a manual entry.
            is_valid, message = looks_like_google_meet_link(row.link)
            if not is_valid:
                return message
        return ""


class ImportReviewDialog(MessageBoxBase):
    """Confirm-before-save review of parsed rows. Sets self.result on accept."""

    def __init__(self, parent, parsed: ParseResult):
        super().__init__(parent)
        self.result: list[Meeting] | None = None

        self.titleLabel = StrongBodyLabel("Review imported classes", self)
        self.viewLayout.addWidget(self.titleLabel)

        # Summary and the select-all shortcuts share one row: dialog height is
        # capped by the parent window, so every row spent on chrome is a row
        # taken from the list the user actually came here to read.
        summary_row = QHBoxLayout()
        summary_row.setSpacing(4)
        self.subtitle = CaptionLabel("", self)
        self.subtitle.setTextColor("#6B7280", "#9CA3AF")
        summary_row.addWidget(self.subtitle)
        summary_row.addStretch(1)
        all_btn = TransparentPushButton("Select all", self)
        all_btn.clicked.connect(lambda: self._set_all(True))
        none_btn = TransparentPushButton("Select none", self)
        none_btn.clicked.connect(lambda: self._set_all(False))
        summary_row.addWidget(all_btn)
        summary_row.addWidget(none_btn)
        self.viewLayout.addLayout(summary_row)

        content = QWidget(self)
        self.list_layout = QVBoxLayout(content)
        self.list_layout.setContentsMargins(0, 0, 4, 0)
        self.list_layout.setSpacing(10)

        self.editors: list[_RowEditor] = []
        for row in parsed.rows:
            editor = _RowEditor(row, content)
            editor.include_box.stateChanged.connect(self._update_subtitle)
            self.list_layout.addWidget(editor)
            self.editors.append(editor)
        self.list_layout.addStretch(1)

        self.scroll_area = ScrollArea(self)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.NoFrame)
        self.scroll_area.setMaximumHeight(_CONTENT_MAX_HEIGHT)
        self.scroll_area.setWidget(content)
        # Must run after setWidget(): it only styles self.widget().
        self.scroll_area.enableTransparentBackground()
        self.viewLayout.addWidget(self.scroll_area)

        privacy = CaptionLabel(
            "The screenshot is discarded when you confirm or cancel — it is "
            "never saved.", self
        )
        privacy.setWordWrap(True)
        privacy.setTextColor("#6B7280", "#9CA3AF")
        self.viewLayout.addWidget(privacy)

        self.widget.setMinimumWidth(780)
        self.yesButton.setText("Add selected classes")
        self.cancelButton.setText("Cancel")

        self._update_subtitle()

    # ---------- internals ----------

    def _set_all(self, checked: bool) -> None:
        for editor in self.editors:
            editor.include_box.setChecked(checked)
        self._update_subtitle()

    def _selected_count(self) -> int:
        return sum(1 for e in self.editors if e.is_included())

    def _update_subtitle(self, *_args) -> None:
        total = len(self.editors)
        chosen = self._selected_count()
        flagged = sum(1 for e in self.editors if e.was_flagged())
        parts = [f"{chosen} of {total} selected"]
        if flagged:
            parts.append(f"{flagged} need a check")
        parts.append("nothing is saved until you confirm")
        self.subtitle.setText("  ·  ".join(parts))

    def _warn(self, title: str, content: str) -> None:
        InfoBar.error(
            title=title, content=content, orient=Qt.Horizontal, isClosable=True,
            position=InfoBarPosition.TOP, duration=4000, parent=self,
        )

    def validate(self) -> bool:
        included = [e for e in self.editors if e.is_included()]
        if not included:
            self._warn("Nothing selected", "Tick at least one class to import.")
            return False

        # Validate every included row before bailing, so the user sees all the
        # problems at once instead of fixing them one dialog at a time.
        first_bad: _RowEditor | None = None
        for editor in self.editors:
            message = editor.validate() if editor.is_included() else ""
            editor.set_error(message)
            if message and first_bad is None:
                first_bad = editor
        if first_bad is not None:
            self.scroll_area.ensureWidgetVisible(first_bad)
            self._warn("Check the highlighted rows", "Some classes still need a fix.")
            return False

        self.result = [import_screenshot.to_meeting(e.to_row()) for e in included]
        return True
