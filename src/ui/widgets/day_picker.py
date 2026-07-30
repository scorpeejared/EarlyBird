"""Apple Clock-style circular day-of-week toggles (Sunday first).

Weekday numbering follows Python's datetime.weekday() (Mon=0 ... Sun=6),
matching src/recurrence.py; only the on-screen order and labels differ.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QVBoxLayout, QWidget

from qfluentwidgets import CaptionLabel, TransparentPushButton, isDarkTheme, setFont

from ... import recurrence

from .. import theme


class _DayToggle(QPushButton):
    """A single circular Sun..Sat toggle button.

    Plain QPushButton styled to match Fluent, not QFluentWidgets'
    PushButton: that constructor dispatches through
    ``singledispatchmethod``, which breaks on the required ``letter``.
    """

    DIAMETER = 34

    def __init__(self, letter: str, parent=None):
        super().__init__(letter, parent)
        setFont(self)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(self.DIAMETER, self.DIAMETER)
        self.toggled.connect(self._apply_style)
        self._apply_style()

    def _apply_style(self, *_args) -> None:
        radius = self.DIAMETER // 2
        if self.isChecked():
            self.setStyleSheet(
                f"QPushButton {{ background-color: {theme.ACCENT}; color: white; "
                f"border: none; border-radius: {radius}px; font-weight: 600; }}"
            )
        else:
            dark = isDarkTheme()
            border = "#3F3F46" if dark else "#E5E7EB"
            hover = "#3A3A3D" if dark else "#F1F2F6"
            text = "#C7C7CC" if dark else "#6B7280"
            self.setStyleSheet(
                f"QPushButton {{ background-color: transparent; color: {text}; "
                f"border: 1px solid {border}; border-radius: {radius}px; }}"
                f"QPushButton:hover {{ background-color: {hover}; }}"
            )


class DayOfWeekPicker(QWidget):
    """Lets the user pick which weekdays a recurring class repeats on."""

    def __init__(self, initial_days: frozenset[int] | None = None, parent=None):
        super().__init__(parent)
        initial = set(initial_days or ())
        self._buttons: dict[int, _DayToggle] = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(8)

        row = QHBoxLayout()
        row.setSpacing(6)
        for weekday, letter in recurrence.APPLE_DAY_ORDER:
            btn = _DayToggle(letter, self)
            btn.setChecked(weekday in initial)
            btn.clicked.connect(self._on_changed)
            row.addWidget(btn)
            self._buttons[weekday] = btn
        row.addStretch(1)
        outer.addLayout(row)

        presets = QHBoxLayout()
        presets.setSpacing(4)
        for label, days in (("Weekdays", recurrence.WEEKDAYS), ("Every day", recurrence.ALL_DAYS)):
            preset_btn = TransparentPushButton(label, self)
            preset_btn.clicked.connect(lambda _checked=False, d=days: self.set_days(d))
            presets.addWidget(preset_btn)
        presets.addStretch(1)
        outer.addLayout(presets)

        self._summary = CaptionLabel(recurrence.format_repeat_label(frozenset(initial)), self)
        self._summary.setTextColor("#6B7280", "#9CA3AF")
        outer.addWidget(self._summary)

    def _on_changed(self) -> None:
        self._summary.setText(recurrence.format_repeat_label(self.get_days()))

    def get_days(self) -> frozenset[int]:
        return frozenset(wd for wd, btn in self._buttons.items() if btn.isChecked())

    def set_days(self, days) -> None:
        days = set(days)
        for weekday, btn in self._buttons.items():
            btn.setChecked(weekday in days)
        self._summary.setText(recurrence.format_repeat_label(frozenset(days)))
