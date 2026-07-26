"""Settings page: app version, update checks, and background behavior."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QButtonGroup, QHBoxLayout, QVBoxLayout, QWidget

from qfluentwidgets import (
    CaptionLabel,
    CardWidget,
    FluentIcon,
    HyperlinkButton,
    PrimaryPushButton,
    PushButton,
    RadioButton,
    StrongBodyLabel,
    SubtitleLabel,
    TransparentPushButton,
)

from .. import theme

REPO_URL = "https://github.com/scorpeejared/EarlyBird"


def _section(title: str, body: str) -> CardWidget:
    card = CardWidget()
    card.setBorderRadius(theme.CARD_RADIUS)
    layout = QVBoxLayout(card)
    layout.setContentsMargins(18, 16, 18, 16)
    layout.setSpacing(4)
    layout.addWidget(StrongBodyLabel(title, card))
    caption = CaptionLabel(body, card)
    caption.setWordWrap(True)
    caption.setTextColor("#6B7280", "#9CA3AF")
    layout.addWidget(caption)
    return card


class SettingsPage(QWidget):
    checkForUpdatesClicked = Signal()
    updateNowClicked = Signal()
    updateLaterClicked = Signal()
    themeModeChanged = Signal(str)  # "light" | "dark" | "auto"

    def __init__(self, app_version: str, theme_mode: str = "light", parent=None):
        super().__init__(parent)
        self.setObjectName("SettingsPage")

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 20)
        root.setSpacing(14)
        root.addWidget(SubtitleLabel("Settings", self))

        version_card = CardWidget(self)
        version_card.setBorderRadius(theme.CARD_RADIUS)
        v_layout = QVBoxLayout(version_card)
        v_layout.setContentsMargins(18, 16, 18, 16)
        v_layout.setSpacing(6)
        v_layout.addWidget(StrongBodyLabel(f"EarlyBird v{app_version}", version_card))
        self.status_label = CaptionLabel("Ready", version_card)
        self.status_label.setTextColor("#6B7280", "#9CA3AF")
        self.status_label.setOpenExternalLinks(True)
        self.status_label.setWordWrap(True)
        v_layout.addWidget(self.status_label)

        self._check_btn = PushButton(FluentIcon.SYNC, "Check for updates now", version_card)
        self._check_btn.clicked.connect(self.checkForUpdatesClicked)
        v_layout.addWidget(self._check_btn)

        # Inline "an update is ready" prompt - hidden until an update is
        # actually found, then replaces the "Check for updates" button
        # so the settings page itself asks "update now or later?"
        # instead of only relying on the corner toast.
        update_row = QHBoxLayout()
        self._update_now_btn = PrimaryPushButton("Update now", version_card)
        self._update_now_btn.clicked.connect(self.updateNowClicked)
        self._update_later_btn = TransparentPushButton("Later", version_card)
        self._update_later_btn.clicked.connect(self.updateLaterClicked)
        update_row.addWidget(self._update_now_btn)
        update_row.addWidget(self._update_later_btn)
        update_row.addStretch(1)
        self._update_now_btn.hide()
        self._update_later_btn.hide()
        v_layout.addLayout(update_row)

        link_btn = HyperlinkButton(REPO_URL, "View project on GitHub", version_card, FluentIcon.GITHUB)
        v_layout.addWidget(link_btn)
        root.addWidget(version_card)

        root.addWidget(self._build_personalization_card(theme_mode))

        root.addWidget(_section(
            "Running in the background",
            "Closing the window offers to minimize EarlyBird to the system tray so it "
            "keeps auto-joining classes quietly. Choose to quit instead from that prompt, "
            "or right-click the tray icon at any time.",
        ))

        root.addWidget(_section(
            "About auto-join",
            "When a class is due, EarlyBird opens (or attaches to) Chrome, joins the "
            "Google Meet link, and mutes the microphone and camera according to each "
            "class's settings. Configure which Chrome window each class uses on the "
            "Connections page.",
        ))

        root.addStretch(1)

    def _build_personalization_card(self, theme_mode: str) -> CardWidget:
        card = CardWidget(self)
        card.setBorderRadius(theme.CARD_RADIUS)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(8)
        layout.addWidget(StrongBodyLabel("Personalization", card))
        caption = CaptionLabel("Choose how EarlyBird looks.", card)
        caption.setTextColor("#6B7280", "#9CA3AF")
        layout.addWidget(caption)

        options_row = QHBoxLayout()
        options_row.setSpacing(16)
        self._light_radio = RadioButton("Light", card)
        self._dark_radio = RadioButton("Dark", card)
        self._auto_radio = RadioButton("Use system setting", card)
        group = QButtonGroup(card)
        for radio in (self._light_radio, self._dark_radio, self._auto_radio):
            group.addButton(radio)
            options_row.addWidget(radio)
        options_row.addStretch(1)
        layout.addLayout(options_row)

        {"light": self._light_radio, "dark": self._dark_radio, "auto": self._auto_radio}.get(
            theme_mode, self._light_radio
        ).setChecked(True)

        self._light_radio.toggled.connect(lambda checked: checked and self.themeModeChanged.emit("light"))
        self._dark_radio.toggled.connect(lambda checked: checked and self.themeModeChanged.emit("dark"))
        self._auto_radio.toggled.connect(lambda checked: checked and self.themeModeChanged.emit("auto"))

        return card

    def set_status(self, text: str) -> None:
        """Plain status text (e.g. 'Checking for updates...', scheduler
        messages). Always safe to call - it does not touch the
        update-now/later buttons, so callers don't need to know whether
        an update prompt is currently showing."""
        self.status_label.setTextFormat(Qt.PlainText)
        self.status_label.setText(text)

    def show_update_available(self, tag: str, html_url: str) -> None:
        """Switch the version card into 'an update is ready' mode: the
        status line becomes a link to the release and the plain 'Check
        for updates' button is replaced by 'Update now' / 'Later'."""
        self.status_label.setTextFormat(Qt.RichText)
        self.status_label.setText(
            f"{theme.link_html(html_url, tag)} is available - update now or later?"
        )
        self._check_btn.hide()
        self._update_now_btn.show()
        self._update_later_btn.show()

    def clear_update_available(self) -> None:
        """Revert to the normal 'Check for updates' button, e.g. after
        the user picks Later, or once an update starts installing."""
        self._update_now_btn.hide()
        self._update_later_btn.hide()
        self._check_btn.show()

