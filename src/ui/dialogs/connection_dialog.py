"""Add/Edit dialog for a single named Chrome connection."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QButtonGroup, QVBoxLayout, QWidget

from qfluentwidgets import (
    CaptionLabel,
    InfoBar,
    InfoBarPosition,
    LineEdit,
    MessageBox,
    MessageBoxBase,
    PushButton,
    RadioButton,
    StrongBodyLabel,
)

from ... import automation_uia, cdp_probe


def _hint(text: str) -> CaptionLabel:
    label = CaptionLabel(text)
    label.setWordWrap(True)
    label.setTextColor("#6B7280", "#9CA3AF")
    return label


def _field(label_text: str, widget: QWidget) -> QVBoxLayout:
    col = QVBoxLayout()
    col.setSpacing(4)
    col.addWidget(CaptionLabel(label_text))
    col.addWidget(widget)
    return col


class ConnectionAddEditDialog(MessageBoxBase):
    """Add or edit a single named Chrome connection. Sets self.result on accept."""

    def __init__(self, parent, existing: dict | None = None):
        super().__init__(parent)
        self.result: dict | None = None
        self._existing = existing

        self.viewLayout.addWidget(
            StrongBodyLabel("Edit connection" if existing else "Add a Chrome connection", self)
        )

        self.name_edit = LineEdit(self)
        self.name_edit.setPlaceholderText("A label just for you, e.g. \"School laptop\"")
        self.name_edit.setText(existing["name"] if existing else "")
        self.viewLayout.addLayout(_field("Name", self.name_edit))

        self.uia_radio = RadioButton(
            "Launch/attach automatically, no manual setup (recommended, Windows only)", self
        )
        self.cdp_radio = RadioButton(
            "Attach via debug port (doesn't work on your real profile since Chrome 136 - see README)", self
        )
        self._backend_group = QButtonGroup(self)
        self._backend_group.addButton(self.uia_radio)
        self._backend_group.addButton(self.cdp_radio)
        backend = existing["backend"] if existing else "uia"
        self.uia_radio.setChecked(backend == "uia")
        self.cdp_radio.setChecked(backend == "cdp")
        self.uia_radio.toggled.connect(self._toggle_backend)
        self.viewLayout.addWidget(self.uia_radio)
        self.viewLayout.addWidget(self.cdp_radio)

        # --- "no setup" (UIA) fields ---
        self.uia_frame = QWidget(self)
        uia_layout = QVBoxLayout(self.uia_frame)
        uia_layout.setContentsMargins(0, 4, 0, 0)
        uia_layout.setSpacing(6)
        self.uia_profile_edit = LineEdit(self)
        self.uia_profile_edit.setText(existing.get("profile_directory", "") if existing else "")
        uia_layout.addLayout(_field("Chrome profile directory name", self.uia_profile_edit))
        uia_layout.addWidget(_hint(
            "Find this via chrome://version in that specific profile's Chrome window - "
            "use the last folder from 'Profile Path', not the display name shown in "
            "Chrome's UI. Once set, this works whether Chrome is already open or closed."
        ))
        uia_layout.addWidget(_hint(
            "Advanced fallback (only used if profile directory above is blank): attach to "
            "an already-open window instead, matched by title."
        ))
        self.title_hint_edit = LineEdit(self)
        self.title_hint_edit.setText(existing.get("title_hint", "") if existing else "")
        uia_layout.addLayout(_field("Window title contains (optional)", self.title_hint_edit))
        detect_btn = PushButton("Detect open Chrome windows", self)
        detect_btn.clicked.connect(self._on_detect)
        uia_layout.addWidget(detect_btn)
        self.viewLayout.addWidget(self.uia_frame)

        # --- "debug port" (CDP) fields ---
        self.cdp_frame = QWidget(self)
        cdp_layout = QVBoxLayout(self.cdp_frame)
        cdp_layout.setContentsMargins(0, 4, 0, 0)
        cdp_layout.setSpacing(6)
        self.cdp_profile_edit = LineEdit(self)
        self.cdp_profile_edit.setText(existing.get("profile_directory", "") if existing else "")
        cdp_layout.addLayout(_field("Chrome profile directory name", self.cdp_profile_edit))
        self.port_edit = LineEdit(self)
        self.port_edit.setText(str(existing.get("port", 9222)) if existing else "9222")
        cdp_layout.addLayout(_field("Debug port (unique per connection)", self.port_edit))
        cdp_layout.addWidget(_hint(
            "Find the profile directory name via chrome://version in that specific "
            "profile's Chrome window - use the last folder from 'Profile Path'."
        ))
        test_btn = PushButton("Test this port", self)
        test_btn.clicked.connect(self._on_test_port)
        cdp_layout.addWidget(test_btn)
        self.viewLayout.addWidget(self.cdp_frame)

        self.status_label = _hint("")
        self.viewLayout.addWidget(self.status_label)

        self.widget.setMinimumWidth(440)
        self.yesButton.setText("Save")
        self.cancelButton.setText("Cancel")

        self._toggle_backend()

    def _toggle_backend(self, *_args) -> None:
        is_uia = self.uia_radio.isChecked()
        self.uia_frame.setVisible(is_uia)
        self.cdp_frame.setVisible(not is_uia)

    def _warn(self, title: str, content: str) -> None:
        InfoBar.error(
            title=title, content=content, orient=Qt.Horizontal, isClosable=True,
            position=InfoBarPosition.TOP, duration=4000, parent=self,
        )

    def _on_detect(self) -> None:
        titles = automation_uia.list_chrome_windows()
        if not titles:
            MessageBox(
                "No Chrome windows found",
                "No open Chrome windows were detected. Open Chrome (any profile) and try "
                "again.\n\n(This detection is Windows-only.)",
                self,
            ).exec()
            return
        listing = "\n".join(f"• {t}" for t in titles)
        MessageBox(
            "Open Chrome windows",
            f"Currently open Chrome windows:\n\n{listing}\n\nCopy a distinctive part of "
            "the one you want into 'Window title contains' above.",
            self,
        ).exec()

    def _on_test_port(self) -> None:
        try:
            port = int(self.port_edit.text())
        except ValueError:
            self._warn("Invalid port", "Port must be a number.")
            return
        info = cdp_probe.probe_port(port, timeout=1.5)
        if info:
            browser = info.get("Browser", "unknown")
            self.status_label.setText(f"✓ Found a live Chrome on port {port} ({browser}).")
        else:
            self.status_label.setText(
                f"✗ Nothing answering on port {port} yet. Run this connection's launcher "
                "script first, then test again."
            )

    def validate(self) -> bool:
        name = self.name_edit.text().strip()
        if not name:
            self._warn("Missing info", "Name is required.")
            return False

        if self.uia_radio.isChecked():
            self.result = {
                "name": name,
                "backend": "uia",
                "profile_directory": automation_uia.normalize_profile_directory(
                    self.uia_profile_edit.text()
                ),
                "title_hint": self.title_hint_edit.text().strip(),
            }
        else:
            profile_directory = automation_uia.normalize_profile_directory(
                self.cdp_profile_edit.text()
            )
            if not profile_directory:
                self._warn("Missing info", "Profile directory name is required.")
                return False
            try:
                port = int(self.port_edit.text())
            except ValueError:
                self._warn("Invalid port", "Port must be a number.")
                return False
            self.result = {
                "name": name, "backend": "cdp",
                "profile_directory": profile_directory, "port": port,
            }
        return True
