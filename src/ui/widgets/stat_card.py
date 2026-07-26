"""Dashboard summary tile, e.g. '3 · Today's Classes'."""
from __future__ import annotations

from PySide6.QtWidgets import QVBoxLayout

from qfluentwidgets import CardWidget, CaptionLabel, IconWidget, TitleLabel

from .. import theme


class StatCard(CardWidget):
    def __init__(self, icon, value: int, label: str, accent: str, parent=None):
        super().__init__(parent)
        self.setBorderRadius(theme.CARD_RADIUS)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 14)
        layout.setSpacing(4)

        icon_widget = IconWidget(icon, self)
        icon_widget.setFixedSize(18, 18)

        self._value_label = TitleLabel(str(value), self)
        self._value_label.setStyleSheet(f"color: {accent};")

        caption = CaptionLabel(label, self)
        caption.setTextColor("#6B7280", "#9CA3AF")

        layout.addWidget(icon_widget)
        layout.addWidget(self._value_label)
        layout.addWidget(caption)
        layout.addStretch(1)

    def set_value(self, value: int) -> None:
        self._value_label.setText(str(value))
