"""Add/Edit dialog for a single named browser connection."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QButtonGroup, QFileDialog, QFrame, QVBoxLayout, QWidget

from qfluentwidgets import (
    CaptionLabel,
    ComboBox,
    FluentIcon,
    InfoBar,
    InfoBarPosition,
    LineEdit,
    MessageBox,
    MessageBoxBase,
    PushButton,
    RadioButton,
    ScrollArea,
    StrongBodyLabel,
)

from ... import automation_uia, browsers, cdp_probe

# The form scrolls past this height instead of growing the dialog: this is a
# MaskDialogBase, which sizes itself to the parent window, so a taller form
# (Opera's folder picker, or the advanced section expanded) is silently
# clipped on a smaller window. Same reason meeting_dialog caps its content.
_CONTENT_MAX_HEIGHT = 400
_DIALOG_WIDTH = 560


def _hint(text: str) -> CaptionLabel:
    label = CaptionLabel(text)
    label.setWordWrap(True)
    label.setTextColor("#6B7280", "#9CA3AF")
    return label


def _field(label_text: str, widget: QWidget) -> QVBoxLayout:
    col, _ = _labeled_field(label_text, widget)
    return col


def _labeled_field(label_text: str, widget: QWidget) -> tuple[QVBoxLayout, CaptionLabel]:
    """Same as _field, but hands back the caption so it can be relabelled
    when the selected browser changes."""
    label = CaptionLabel(label_text)
    col = QVBoxLayout()
    col.setSpacing(4)
    col.addWidget(label)
    col.addWidget(widget)
    return col, label


class ConnectionAddEditDialog(MessageBoxBase):
    """Add or edit a single named Chrome connection. Sets self.result on accept."""

    def __init__(self, parent, existing: dict | None = None):
        super().__init__(parent)
        self.result: dict | None = None
        self._existing = existing

        self.viewLayout.addWidget(
            StrongBodyLabel("Edit connection" if existing else "Add a browser connection", self)
        )

        # Everything below the title lives in the scrolling content area -
        # see _CONTENT_MAX_HEIGHT.
        content = QWidget(self)
        form = QVBoxLayout(content)
        # Right margin keeps the fields clear of the scrollbar, which overlays.
        form.setContentsMargins(0, 0, 14, 0)
        form.setSpacing(10)

        self.name_edit = LineEdit(self)
        self.name_edit.setPlaceholderText("A label just for you, e.g. \"School laptop\"")
        self.name_edit.setText(existing["name"] if existing else "")
        form.addLayout(_field("Name", self.name_edit))

        # Browser picker. Chrome is first and preselected, so an existing
        # connection - or anyone who just clicks through - lands on Chrome.
        self.browser_combo = ComboBox(self)
        for browser_id in browsers.SUPPORTED:
            self.browser_combo.addItem(browsers.display_name(browser_id), userData=browser_id)
        current_browser = browsers.normalize(existing.get("browser") if existing else None)
        if current_browser not in browsers.SUPPORTED:
            current_browser = browsers.DEFAULT
        self.browser_combo.setCurrentIndex(browsers.SUPPORTED.index(current_browser))
        self.browser_combo.currentIndexChanged.connect(self._on_browser_changed)
        form.addLayout(_field("Browser", self.browser_combo))

        # Only visible for a browser that behaves differently from the others.
        self.compat_label = _hint("")
        form.addWidget(self.compat_label)

        self.uia_radio = RadioButton("Launch automatically - no setup (recommended)", self)
        self.cdp_radio = RadioButton("Attach via debug port (advanced)", self)
        self._backend_group = QButtonGroup(self)
        self._backend_group.addButton(self.uia_radio)
        self._backend_group.addButton(self.cdp_radio)
        backend = existing["backend"] if existing else "uia"
        self.uia_radio.setChecked(backend == "uia")
        self.cdp_radio.setChecked(backend == "cdp")
        self.uia_radio.toggled.connect(self._toggle_backend)
        form.addWidget(self.uia_radio)
        form.addWidget(self.cdp_radio)
        self.backend_hint = _hint("")
        form.addWidget(self.backend_hint)

        # --- "no setup" (UIA) fields ---
        self.uia_frame = QWidget(self)
        uia_layout = QVBoxLayout(self.uia_frame)
        uia_layout.setContentsMargins(0, 4, 0, 0)
        uia_layout.setSpacing(6)
        self.uia_profile_edit = LineEdit(self)
        self.uia_profile_edit.setText(existing.get("profile_directory", "") if existing else "")
        uia_field, self.uia_profile_label = _labeled_field(
            "Chrome profile directory name", self.uia_profile_edit
        )
        uia_layout.addLayout(uia_field)
        # Only shown in single-profile-folder mode (Opera), where the field
        # holds a real directory path rather than a profile name.
        self.browse_btn = PushButton("Browse for profile folder...", self)
        self.browse_btn.clicked.connect(lambda: self._on_browse(self.uia_profile_edit))
        uia_layout.addWidget(self.browse_btn)
        self.uia_hint = _hint("")
        uia_layout.addWidget(self.uia_hint)
        # Live read-out of how the pasted path splits, so a wrong level is
        # obvious before saving rather than after a class fails to join.
        self.resolved_label = _hint("")
        uia_layout.addWidget(self.resolved_label)
        self.uia_profile_edit.textChanged.connect(self._update_resolved_profile)

        # The title-based fallback is rarely needed, so it starts collapsed -
        # unless this connection actually uses it, in which case hiding the
        # saved value would be worse than the extra height.
        self.advanced_toggle = PushButton(
            FluentIcon.CHEVRON_RIGHT_MED, "Advanced: attach by window title", self)
        self.advanced_toggle.setCheckable(True)
        self.advanced_toggle.toggled.connect(self._toggle_advanced)
        uia_layout.addWidget(self.advanced_toggle)

        self.advanced_frame = QWidget(self)
        advanced_layout = QVBoxLayout(self.advanced_frame)
        advanced_layout.setContentsMargins(0, 0, 0, 0)
        advanced_layout.setSpacing(6)
        self.fallback_hint = _hint(
            "Used only when the field above is blank: attach to an already-open "
            "window, matched by title."
        )
        advanced_layout.addWidget(self.fallback_hint)
        self.title_hint_edit = LineEdit(self)
        self.title_hint_edit.setText(existing.get("title_hint", "") if existing else "")
        advanced_layout.addLayout(_field("Window title contains", self.title_hint_edit))
        self.detect_btn = PushButton("Detect open Chrome windows", self)
        self.detect_btn.clicked.connect(self._on_detect)
        advanced_layout.addWidget(self.detect_btn)
        uia_layout.addWidget(self.advanced_frame)
        self.advanced_toggle.setChecked(bool(existing and existing.get("title_hint")))
        self._toggle_advanced(self.advanced_toggle.isChecked())

        form.addWidget(self.uia_frame)

        # --- "debug port" (CDP) fields ---
        self.cdp_frame = QWidget(self)
        cdp_layout = QVBoxLayout(self.cdp_frame)
        cdp_layout.setContentsMargins(0, 4, 0, 0)
        cdp_layout.setSpacing(6)
        self.cdp_profile_edit = LineEdit(self)
        self.cdp_profile_edit.setText(existing.get("profile_directory", "") if existing else "")
        cdp_field, self.cdp_profile_label = _labeled_field(
            "Chrome profile directory name", self.cdp_profile_edit
        )
        cdp_layout.addLayout(cdp_field)
        self.cdp_browse_btn = PushButton("Browse for profile folder...", self)
        self.cdp_browse_btn.clicked.connect(lambda: self._on_browse(self.cdp_profile_edit))
        cdp_layout.addWidget(self.cdp_browse_btn)
        self.port_edit = LineEdit(self)
        self.port_edit.setText(str(existing.get("port", 9222)) if existing else "9222")
        cdp_layout.addLayout(_field("Debug port (unique per connection)", self.port_edit))
        self.cdp_hint = _hint("")
        cdp_layout.addWidget(self.cdp_hint)
        test_btn = PushButton("Test this port", self)
        test_btn.clicked.connect(self._on_test_port)
        cdp_layout.addWidget(test_btn)
        form.addWidget(self.cdp_frame)

        self.status_label = _hint("")
        form.addWidget(self.status_label)
        form.addStretch(1)

        self.scroll_area = ScrollArea(self)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.NoFrame)
        self.scroll_area.setMaximumHeight(_CONTENT_MAX_HEIGHT)
        self.scroll_area.setWidget(content)
        # Must run after setWidget(): it only styles self.widget().
        self.scroll_area.enableTransparentBackground()
        self.viewLayout.addWidget(self.scroll_area)

        self.widget.setFixedWidth(_DIALOG_WIDTH)
        self.yesButton.setText("Save")
        self.cancelButton.setText("Cancel")

        self._on_browser_changed()
        self._toggle_backend()

    def _toggle_advanced(self, expanded: bool) -> None:
        self.advanced_frame.setVisible(expanded)
        # An icon rather than a text arrow: the glyphs render as tofu in the
        # UI font.
        self.advanced_toggle.setIcon(
            FluentIcon.CHEVRON_DOWN_MED if expanded else FluentIcon.CHEVRON_RIGHT_MED)

    def selected_browser(self) -> str:
        return browsers.normalize(self.browser_combo.currentData())

    def _on_browse(self, target) -> None:
        """Pick the browser's profile folder (single-profile-folder mode only)."""
        start = target.text().strip() or browsers.default_profile_dir(self.selected_browser())
        chosen = QFileDialog.getExistingDirectory(self, "Select the profile folder", start)
        if chosen:
            # QFileDialog hands back forward slashes even on Windows.
            target.setText(str(Path(chosen)))

    def _update_resolved_profile(self, *_args) -> None:
        """Show which folder is the user-data-dir and which is the profile."""
        browser = self.selected_browser()
        text = self.uia_profile_edit.text().strip()
        if not browsers.uses_single_profile_dir(browser) or not text:
            self.resolved_label.setText("")
            self.resolved_label.setVisible(False)
            return
        user_data_dir, profile_directory = browsers.split_profile_path(text)
        if profile_directory:
            message = f"Will open profile '{profile_directory}' in {user_data_dir}"
        else:
            message = (
                f"Will open {user_data_dir} directly. If that isn't the profile you "
                f"expect, paste the full path from {browsers.version_page(browser)} instead."
            )
        self.resolved_label.setText(message)
        self.resolved_label.setVisible(True)

    def _on_browser_changed(self, *_args) -> None:
        """Point the profile instructions at whichever browser is selected.

        Two profile-picker modes: Chromium's profile *name* inside a shared
        User Data folder, or Opera's single profile *folder* per install.
        """
        browser = self.selected_browser()
        label = browsers.short_name(browser)
        version_page = browsers.version_page(browser)
        single_dir = browsers.uses_single_profile_dir(browser)

        if single_dir:
            field_label = f"{label} profile folder"
            example = browsers.default_profile_dir(browser)
            shared_hint = (
                f"Copy the whole 'Profile' path from {version_page}, including the "
                "trailing \\Default - both halves are needed, and they get split for you."
            )
            self.uia_profile_edit.setPlaceholderText(example)
            self.cdp_profile_edit.setPlaceholderText(example)
        else:
            field_label = f"{label} profile directory name"
            shared_hint = (
                f"The last folder of 'Profile Path' on {version_page} (e.g. Profile 1) - "
                f"not the name {label} shows in its UI."
            )
            self.uia_profile_edit.setPlaceholderText("")
            self.cdp_profile_edit.setPlaceholderText("")
        self.uia_hint.setText(shared_hint)
        self.cdp_hint.setText(shared_hint)

        self.uia_profile_label.setText(field_label)
        self.cdp_profile_label.setText(field_label)
        self.browse_btn.setVisible(single_dir)
        self.cdp_browse_btn.setVisible(single_dir)
        self.detect_btn.setText(f"Detect open {label} windows")
        self._update_resolved_profile()

        note = browsers.compatibility_note(browser)
        self.compat_label.setText(f"Note: {note}" if note else "")
        self.compat_label.setVisible(bool(note))
        # The backend caption names the browser, so it follows this too.
        self._toggle_backend()

    def _toggle_backend(self, *_args) -> None:
        is_uia = self.uia_radio.isChecked()
        self.uia_frame.setVisible(is_uia)
        self.cdp_frame.setVisible(not is_uia)
        # The radio labels stay short; the caveat that used to live in them
        # sits here instead, and only for the option actually selected.
        label = browsers.short_name(self.selected_browser())
        self.backend_hint.setText(
            f"Windows only. Opens the profile below when a class is due, whether "
            f"{label} is already running or not."
            if is_uia else
            f"Needs {label} started from a generated launcher script rather than its "
            "normal icon. Since Chrome 136 the debug port is refused for your real "
            "default profile - see the README."
        )

    def _warn(self, title: str, content: str) -> None:
        InfoBar.error(
            title=title, content=content, orient=Qt.Horizontal, isClosable=True,
            position=InfoBarPosition.TOP, duration=4000, parent=self,
        )

    def _on_detect(self) -> None:
        label = browsers.short_name(self.selected_browser())
        titles = automation_uia.list_browser_windows(self.selected_browser())
        if not titles:
            MessageBox(
                f"No {label} windows found",
                f"No open {label} windows were detected. Open {label} (any profile) and try "
                "again.\n\n(This detection is Windows-only.)",
                self,
            ).exec()
            return
        listing = "\n".join(f"• {t}" for t in titles)
        MessageBox(
            f"Open {label} windows",
            f"Currently open {label} windows:\n\n{listing}\n\nCopy a distinctive part of "
            "the one you want into 'Window title contains' above.",
            self,
        ).exec()

    def _on_test_port(self) -> None:
        try:
            port = int(self.port_edit.text())
        except ValueError:
            self._warn("Invalid port", "Port must be a number.")
            return
        label = browsers.short_name(self.selected_browser())
        info = cdp_probe.probe_port(port, timeout=1.5)
        if info:
            reported = info.get("Browser", "unknown")
            self.status_label.setText(f"✓ Found a live {label} on port {port} ({reported}).")
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

        browser = self.selected_browser()

        if self.uia_radio.isChecked():
            self.result = {
                "name": name,
                "backend": "uia",
                "browser": browser,
                "profile_directory": automation_uia.normalize_profile_setting(
                    self.uia_profile_edit.text(), browser
                ),
                "title_hint": self.title_hint_edit.text().strip(),
            }
        else:
            profile_directory = automation_uia.normalize_profile_setting(
                self.cdp_profile_edit.text(), browser
            )
            if not profile_directory:
                self._warn(
                    "Missing info",
                    "Profile folder is required." if browsers.uses_single_profile_dir(browser)
                    else "Profile directory name is required.",
                )
                return False
            try:
                port = int(self.port_edit.text())
            except ValueError:
                self._warn("Invalid port", "Port must be a number.")
                return False
            self.result = {
                "name": name, "backend": "cdp", "browser": browser,
                "profile_directory": profile_directory, "port": port,
            }
        return True
