"""Add/Edit dialog for a single scheduled class."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from urllib.parse import urlparse

from PySide6.QtCore import (
    QDate, QTime, Qt, QPropertyAnimation, QEasingCurve, QThread, QTimer, Signal,
)
from PySide6.QtWidgets import QFrame, QHBoxLayout, QVBoxLayout, QWidget

from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    ComboBox,
    DatePicker,
    FluentIcon,
    InfoBar,
    InfoBarPosition,
    LineEdit,
    MessageBoxBase,
    PushButton,
    ScrollArea,
    SpinBox,
    StrongBodyLabel,
    SwitchButton,
    TimePicker,
)

from ... import recurrence, scheduler, settings
from ...models import Meeting

from ..widgets.day_picker import DayOfWeekPicker

# The content area scrolls at this height instead of growing the dialog:
# MaskDialogBase sizes itself to the parent window, so a taller form
# (e.g. once Repeat weekly reveals the day picker) is silently clipped.
_CONTENT_MAX_HEIGHT = 400


def _field(label_text: str, widget: QWidget) -> QVBoxLayout:
    col = QVBoxLayout()
    col.setSpacing(4)
    col.addWidget(CaptionLabel(label_text))
    col.addWidget(widget)
    return col


# Test-run threads are deliberately not parented to the dialog: a join can
# outlive the dialog that started it, and destroying a running QThread with
# its parent crashes. They're held here until they finish instead.
_running_test_threads: set = set()


class _TestRunWorker(QThread):
    """Runs one real join off the GUI thread.

    The automation blocks for tens of seconds (browser launch, page load,
    the verification pass), which would freeze the dialog if run inline.
    """

    done = Signal(bool, str)

    def __init__(self, meeting: Meeting, parent=None):
        super().__init__(parent)
        self._meeting = meeting

    def run(self) -> None:
        try:
            result = scheduler.perform_join(self._meeting)
            self.done.emit(result.success, result.message)
        except Exception as e:  # noqa: BLE001 - a crash here must not kill the dialog
            self.done.emit(False, f"Test run failed: {e}")


def looks_like_google_meet_link(text: str) -> tuple[bool, str]:
    """Returns (is_valid, error_message).

    Public because the screenshot-import review screen validates the same
    links; one rule, one place.
    """
    try:
        parsed = urlparse(text)
    except ValueError:
        return False, "That doesn't look like a valid link."
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return False, "Enter a full link starting with https://, not plain text."
    host = parsed.netloc.lower().split(":")[0]
    if host not in ("meet.google.com", "www.meet.google.com"):
        return False, "That link isn't a meet.google.com address."
    return True, ""


class MeetingDialog(MessageBoxBase):
    """Add/Edit dialog for a single meeting. Sets self.result on accept."""

    def __init__(self, parent, meeting: Meeting | None = None):
        super().__init__(parent)
        self.result: Meeting | None = None
        self._meeting = meeting

        self.titleLabel = StrongBodyLabel(
            "Edit class" if meeting else "Add a new class", self
        )
        self.viewLayout.addWidget(self.titleLabel)

        # All form fields live in the scrollable content area, not
        # directly in viewLayout - see _CONTENT_MAX_HEIGHT above.
        content = QWidget(self)
        form = QVBoxLayout(content)
        form.setContentsMargins(0, 0, 4, 0)
        form.setSpacing(12)

        self.title_edit = LineEdit(self)
        self.title_edit.setPlaceholderText("e.g. Calculus 101")
        self.title_edit.setText(meeting.title if meeting else "")
        form.addLayout(_field("Title", self.title_edit))

        self.link_edit = LineEdit(self)
        self.link_edit.setPlaceholderText("https://meet.google.com/xxx-yyyy-zzz")
        self.link_edit.setText(meeting.link if meeting else "")
        form.addLayout(_field("Google Meet link", self.link_edit))

        default_dt = meeting.scheduled_time if meeting else datetime.now()
        is_repeat = recurrence.is_recurring(meeting) if meeting else False
        initial_days = recurrence.parse_days(meeting.recurring_days) if meeting else frozenset()

        date_time_row = QHBoxLayout()
        self.date_picker = DatePicker(self)
        self.date_picker.setDate(QDate(default_dt.year, default_dt.month, default_dt.day))
        self.date_label = CaptionLabel("Date", self)
        date_col = QVBoxLayout()
        date_col.setSpacing(4)
        date_col.addWidget(self.date_label)
        date_col.addWidget(self.date_picker)
        date_time_row.addLayout(date_col, 1)

        self.time_picker = TimePicker(self)
        self.time_picker.setTime(QTime(default_dt.hour, default_dt.minute))
        date_time_row.addLayout(_field("Time", self.time_picker), 1)
        form.addLayout(date_time_row)

        switches_row = QHBoxLayout()
        self.auto_join_switch = SwitchButton(self)
        self.auto_join_switch.setChecked(meeting.auto_join if meeting else True)
        switches_row.addLayout(_labeled_switch("Auto-join at scheduled time", self.auto_join_switch))
        form.addLayout(switches_row)

        mute_row = QHBoxLayout()
        self.mic_switch = SwitchButton(self)
        self.mic_switch.setChecked(meeting.mute_mic if meeting else True)
        mute_row.addLayout(_labeled_switch("Mute microphone on join", self.mic_switch), 1)
        self.cam_switch = SwitchButton(self)
        self.cam_switch.setChecked(meeting.mute_camera if meeting else True)
        mute_row.addLayout(_labeled_switch("Turn off camera on join", self.cam_switch), 1)
        form.addLayout(mute_row)

        early_row = QHBoxLayout()
        self.join_early_spin = SpinBox(self)
        self.join_early_spin.setRange(0, 60)
        self.join_early_spin.setValue(meeting.join_early_minutes if meeting else 0)
        early_row.addLayout(_field("Join early (minutes)", self.join_early_spin))
        form.addLayout(early_row)
        hint = CaptionLabel("0 = join exactly at the scheduled time", self)
        hint.setTextColor("#6B7280", "#9CA3AF")
        form.addWidget(hint)

        repeat_row = QHBoxLayout()
        self.repeat_switch = SwitchButton(self)
        self.repeat_switch.setChecked(is_repeat)
        self.repeat_switch.checkedChanged.connect(self._toggle_repeat)
        repeat_row.addLayout(_labeled_switch("Repeat weekly", self.repeat_switch))
        form.addLayout(repeat_row)

        self.day_picker = DayOfWeekPicker(initial_days, self)
        form.addWidget(self.day_picker)

        self.connection_combo = ComboBox(self)
        names = settings.connection_names()
        self.connection_combo.addItems(names)
        current_name = meeting.browser_connection if meeting and meeting.browser_connection else None
        default_label = current_name if current_name in names else settings.ISOLATED_PROFILE_LABEL
        self.connection_combo.setCurrentText(default_label)
        form.addLayout(_field("Join using", self.connection_combo))

        # Test run: the same join the scheduler performs, on demand, so the
        # setup can be proven before a class actually depends on it.
        self._test_thread: _TestRunWorker | None = None
        self.finished.connect(self._detach_test_thread)
        self.test_button = PushButton(FluentIcon.PLAY, "Test run now", self)
        self.test_button.clicked.connect(self._on_test_run)
        form.addWidget(self.test_button)
        self.test_hint = CaptionLabel(
            "Opens the browser and joins this meeting for real, right now - "
            "same steps as the scheduled join. Nothing is saved by testing.", self
        )
        self.test_hint.setWordWrap(True)
        self.test_hint.setTextColor("#6B7280", "#9CA3AF")
        form.addWidget(self.test_hint)

        self.scroll_area = ScrollArea(self)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.NoFrame)
        self.scroll_area.setMaximumHeight(_CONTENT_MAX_HEIGHT)
        self.scroll_area.setWidget(content)
        # Must run after setWidget(): it only styles self.widget().
        self.scroll_area.enableTransparentBackground()
        self.viewLayout.addWidget(self.scroll_area)

        self._scroll_animation = QPropertyAnimation(self.scroll_area.verticalScrollBar(), b"value")
        self._scroll_animation.setDuration(300)
        self._scroll_animation.setEasingCurve(QEasingCurve.OutCubic)

        self.widget.setMinimumWidth(600)
        self.yesButton.setText("Save")
        self.cancelButton.setText("Cancel")

        self._toggle_repeat(is_repeat)

    def _toggle_repeat(self, repeating: bool) -> None:
        self.day_picker.setVisible(repeating)
        self.date_label.setText("Starting from" if repeating else "Date")
        # Let the layout recalculate the content height before scrolling.
        QTimer.singleShot(50, lambda: self._smooth_scroll_to_bottom() if repeating else self._smooth_scroll_to_top())

    def _smooth_scroll_to_bottom(self) -> None:
        scrollbar = self.scroll_area.verticalScrollBar()
        if scrollbar.maximum() > 0:
            self._scroll_animation.setStartValue(scrollbar.value())
            self._scroll_animation.setEndValue(scrollbar.maximum())
            self._scroll_animation.start()

    def _smooth_scroll_to_top(self) -> None:
        scrollbar = self.scroll_area.verticalScrollBar()
        if scrollbar.value() > 0:
            self._scroll_animation.setStartValue(scrollbar.value())
            self._scroll_animation.setEndValue(0)
            self._scroll_animation.start()

    def _warn(self, title: str, content: str) -> None:
        InfoBar.error(
            title=title, content=content, orient=Qt.Horizontal, isClosable=True,
            position=InfoBarPosition.TOP, duration=4000, parent=self,
        )

    def _on_test_run(self) -> None:
        """Join this meeting right now, exactly as the scheduler would."""
        if self._test_thread and self._test_thread.isRunning():
            return
        # validate() builds the Meeting from the form and warns about
        # anything missing, so a test run can't be started on a bad link.
        if not self.validate():
            return

        candidate = self.result
        # A test must never look like a real join to the scheduler: strip the
        # id and the joined/notified bookkeeping from the throwaway copy.
        trial = replace(candidate, id=None, notified=False, joined=False,
                        last_notified_date="", last_joined_date="")

        self.test_button.setEnabled(False)
        self.test_button.setText("Test run in progress...")
        InfoBar.info(
            title="Test run started",
            content="Opening the browser and joining now. This can take up to a minute.",
            orient=Qt.Horizontal, isClosable=True, position=InfoBarPosition.TOP,
            duration=4000, parent=self,
        )

        worker = _TestRunWorker(trial)
        _running_test_threads.add(worker)
        worker.finished.connect(lambda w=worker: _running_test_threads.discard(w))
        worker.done.connect(self._on_test_finished)
        self._test_thread = worker
        worker.start()

    def _detach_test_thread(self, *_args) -> None:
        """Stop a still-running test from calling back into a closing dialog."""
        if self._test_thread and self._test_thread.isRunning():
            try:
                self._test_thread.done.disconnect(self._on_test_finished)
            except (RuntimeError, TypeError):
                pass  # already disconnected, or the signal never fired

    def _on_test_finished(self, success: bool, message: str) -> None:
        self.test_button.setEnabled(True)
        self.test_button.setText("Test run now")
        if success:
            InfoBar.success(
                title="Test run succeeded",
                content="Joined with your mic and camera settings applied. "
                        "The scheduled join will do exactly this.",
                orient=Qt.Horizontal, isClosable=True, position=InfoBarPosition.TOP,
                duration=6000, parent=self,
            )
        else:
            self._warn("Test run failed", message)

    def validate(self) -> bool:
        title = self.title_edit.text().strip()
        link = self.link_edit.text().strip()
        if not title:
            self._warn("Missing info", "Title is required.")
            return False
        if not link:
            self._warn("Missing info", "Google Meet link is required.")
            return False

        is_valid, error_message = looks_like_google_meet_link(link)
        if not is_valid:
            self._warn("Invalid link", error_message)
            return False

        qdate = self.date_picker.getDate()
        qtime = self.time_picker.getTime()
        try:
            scheduled = datetime(
                qdate.year(), qdate.month(), qdate.day(), qtime.hour(), qtime.minute()
            )
        except ValueError:
            self._warn("Invalid date/time", "Please pick a valid date and time.")
            return False

        repeating = self.repeat_switch.isChecked()
        if repeating:
            days = self.day_picker.get_days()
            if not days:
                self._warn("No repeat days", "Select at least one day of the week, or turn off Repeat.")
                return False
            recurring = recurrence.RECURRING_WEEKLY
            recurring_days = recurrence.serialize_days(days)
        else:
            recurring = recurrence.RECURRING_NONE
            recurring_days = ""

        join_early_minutes = self.join_early_spin.value()

        chosen = self.connection_combo.currentText()
        browser_connection = "" if chosen == settings.ISOLATED_PROFILE_LABEL else chosen
        # The connection owns the browser choice; the isolated profile is
        # always Chrome (what it has always been).
        chosen_conn = settings.get_connection(browser_connection) if browser_connection else None
        browser = settings.connection_browser(chosen_conn)

        self.result = Meeting(
            id=self._meeting.id if self._meeting else None,
            title=title,
            link=link,
            scheduled_time=scheduled,
            auto_join=self.auto_join_switch.isChecked(),
            mute_mic=self.mic_switch.isChecked(),
            mute_camera=self.cam_switch.isChecked(),
            recurring=recurring,
            recurring_days=recurring_days,
            join_early_minutes=join_early_minutes,
            notified=self._meeting.notified if self._meeting else False,
            joined=self._meeting.joined if self._meeting else False,
            last_notified_date=self._meeting.last_notified_date if self._meeting else "",
            last_joined_date=self._meeting.last_joined_date if self._meeting else "",
            browser_connection=browser_connection,
            browser=browser,
        )
        return True


def _labeled_switch(label_text: str, switch: SwitchButton) -> QHBoxLayout:
    row = QHBoxLayout()
    row.setSpacing(10)
    row.addWidget(BodyLabel(label_text))
    row.addWidget(switch)
    row.addStretch(1)
    return row
