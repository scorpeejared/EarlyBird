"""'An update is available' card, docked in a corner of the app window.

A child QWidget of MainWindow rather than a top-level window, so it
follows the parent around and stays inside the app's own client area.
No release notes, so it can't grow tall enough to obscure the page
behind it.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from qfluentwidgets import (
    CardWidget,
    CaptionLabel,
    FluentIcon,
    PrimaryPushButton,
    StrongBodyLabel,
    TransparentPushButton,
    TransparentToolButton,
)

from .. import theme


class UpdateToast(QWidget):
    WIDTH, HEIGHT = 340, 130
    MARGIN = 20

    def __init__(self, parent: QWidget, current_version: str, release, on_restart, on_later):
        super().__init__(parent)
        self._on_restart = on_restart
        self._on_later = on_later

        self.setFixedSize(self.WIDTH, self.HEIGHT)
        self.setAttribute(Qt.WA_TranslucentBackground)
        parent.installEventFilter(self)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        card = CardWidget(self)
        card.setBorderRadius(10)
        outer.addWidget(card)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)

        header = QHBoxLayout()
        header.addWidget(StrongBodyLabel("🐦 EarlyBird Update Available", card))
        header.addStretch(1)
        close_btn = TransparentToolButton(FluentIcon.CLOSE, card)
        close_btn.clicked.connect(self._later)
        header.addWidget(close_btn)
        layout.addLayout(header)

        info = CaptionLabel(card)
        info.setWordWrap(True)
        info.setOpenExternalLinks(True)
        if release.html_url:
            info.setTextFormat(Qt.RichText)
            info.setText(
                f"{theme.link_html(release.html_url, release.tag)} is available "
                f"(you have {current_version})."
            )
        else:
            info.setText(f"Version {release.tag} is available (you have {current_version}).")
        layout.addWidget(info)

        self._status_label = CaptionLabel("", card)
        self._status_label.setTextColor("#6B7280", "#9CA3AF")
        self._status_label.setWordWrap(True)
        layout.addWidget(self._status_label)

        layout.addStretch(1)

        footer = QHBoxLayout()
        footer.addStretch(1)
        self._later_btn = TransparentPushButton("Later", card)
        self._later_btn.clicked.connect(self._later)
        self._restart_btn = PrimaryPushButton("Restart && Update", card)
        self._restart_btn.clicked.connect(self._restart)
        footer.addWidget(self._later_btn)
        footer.addWidget(self._restart_btn)
        layout.addLayout(footer)

        self._reposition()

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 (Qt override)
        if obj is self.parentWidget() and event.type() == QEvent.Resize:
            self._reposition()
        return super().eventFilter(obj, event)

    def _reposition(self) -> None:
        parent = self.parentWidget()
        if parent is None:
            return
        x = max(0, parent.width() - self.WIDTH - self.MARGIN)
        y = max(0, parent.height() - self.HEIGHT - self.MARGIN)
        self.move(x, y)

    def showEvent(self, event) -> None:
        self._reposition()
        self.raise_()
        super().showEvent(event)

    def _restart(self) -> None:
        self._on_restart()

    def _later(self) -> None:
        self._on_later()
        self.close()
