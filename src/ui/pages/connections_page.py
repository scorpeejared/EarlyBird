"""Chrome connections page: manage named Chrome windows classes join through."""
from __future__ import annotations

import subprocess
import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractItemView, QHBoxLayout, QTableWidgetItem, QVBoxLayout, QWidget

from qfluentwidgets import (
    CaptionLabel,
    FluentIcon,
    InfoBar,
    InfoBarPosition,
    MessageBox,
    PrimaryPushButton,
    PushButton,
    SubtitleLabel,
    TableWidget,
)

from src import automation_uia, cdp_probe, launchers, settings

from ..dialogs.connection_dialog import ConnectionAddEditDialog


class ConnectionsPage(QWidget):
    """Manage the list of named Chrome connections classes can join through."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ConnectionsPage")

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 20)
        root.setSpacing(14)

        header = QVBoxLayout()
        header.setSpacing(2)
        header.addWidget(SubtitleLabel("Chrome connections", self))
        subtitle = CaptionLabel(
            "Each connection is a Chrome window auto-join attaches to - nothing closes, "
            "nothing relaunches. 'No setup' connections use whatever Chrome window you "
            "already have open; 'debug port' connections need a launcher script but can "
            "target one profile precisely among several.",
            self,
        )
        subtitle.setWordWrap(True)
        subtitle.setTextColor("#6B7280", "#9CA3AF")
        header.addWidget(subtitle)
        root.addLayout(header)

        self.table = TableWidget(self)
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["Name", "Type", "Detail", "Status"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        root.addWidget(self.table, 1)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        add_btn = PrimaryPushButton(FluentIcon.ADD, "Add", self)
        add_btn.clicked.connect(self._on_add)
        edit_btn = PushButton(FluentIcon.EDIT, "Edit", self)
        edit_btn.clicked.connect(self._on_edit)
        remove_btn = PushButton(FluentIcon.DELETE, "Remove", self)
        remove_btn.clicked.connect(self._on_remove)
        status_btn = PushButton(FluentIcon.SYNC, "Check status", self)
        status_btn.clicked.connect(self.refresh)
        scan_btn = PushButton(FluentIcon.WIFI, "Scan for CDP ports", self)
        scan_btn.clicked.connect(self._on_scan)
        folder_btn = PushButton(FluentIcon.FOLDER, "Open launcher folder", self)
        folder_btn.clicked.connect(self._open_launcher_folder)
        for b in (add_btn, edit_btn, remove_btn, status_btn, scan_btn, folder_btn):
            toolbar.addWidget(b)
        toolbar.addStretch(1)
        root.addLayout(toolbar)

        self.refresh()

    def refresh(self) -> None:
        self.table.setRowCount(0)
        open_titles = None
        connections = settings.list_connections()
        self.table.setRowCount(len(connections))
        for row, c in enumerate(connections):
            if c["backend"] == "cdp":
                info = cdp_probe.probe_port(c["port"], timeout=0.5)
                status = "● Running" if info else "○ Not detected"
                detail = f"port {c['port']}"
                backend_label = "Debug port"
            elif c.get("profile_directory"):
                status = "● Ready (launches on demand)"
                detail = f"profile '{c['profile_directory']}'"
                backend_label = "No setup"
            else:
                if open_titles is None:
                    open_titles = automation_uia.list_chrome_windows()
                hint = c.get("title_hint", "")
                matched = any(hint.lower() in t.lower() for t in open_titles) if hint else bool(open_titles)
                status = "● Chrome open" if matched else "○ Chrome not open"
                detail = f"title has '{hint}'" if hint else "(any open window)"
                backend_label = "No setup (attach)"

            for col, value in enumerate([c["name"], backend_label, detail, status]):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, c["name"])
                self.table.setItem(row, col, item)

    def _selected_name(self) -> str | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        return item.data(Qt.UserRole) if item else None

    def _info(self, title: str, content: str) -> None:
        InfoBar.success(
            title=title, content=content, orient=Qt.Horizontal, isClosable=True,
            position=InfoBarPosition.TOP, duration=5000, parent=self.window(),
        )

    def _warn(self, title: str, content: str) -> None:
        InfoBar.warning(
            title=title, content=content, orient=Qt.Horizontal, isClosable=True,
            position=InfoBarPosition.TOP, duration=4000, parent=self.window(),
        )

    def _on_add(self) -> None:
        dlg = ConnectionAddEditDialog(self.window())
        if dlg.exec() and dlg.result:
            self._save_and_generate(dlg.result)

    def _on_edit(self) -> None:
        name = self._selected_name()
        if not name:
            self._warn("No selection", "Select a connection to edit first.")
            return
        existing = settings.get_connection(name)
        dlg = ConnectionAddEditDialog(self.window(), existing=existing)
        if dlg.exec() and dlg.result:
            if dlg.result["name"] != name:
                settings.remove_connection(name)
                launchers.remove_launchers(name)
            self._save_and_generate(dlg.result)

    def _save_and_generate(self, result: dict) -> None:
        if result["backend"] == "uia":
            settings.add_or_update_uia_connection(
                result["name"], result.get("title_hint", ""), result.get("profile_directory", "")
            )
            self.refresh()
            if result.get("profile_directory"):
                msg = (
                    "No launcher needed - Chrome can be open or closed, this connection "
                    "launches that profile fresh either way. Pick it for any class in "
                    "Add/Edit class."
                )
            else:
                msg = (
                    "No profile directory set, so this will only work if Chrome is already "
                    "open with a matching window at class time. Consider adding a profile "
                    "directory for a more reliable setup."
                )
            self._info("Connection saved", msg)
        else:
            settings.add_or_update_cdp_connection(result["name"], result["profile_directory"], result["port"])
            bat_path, sh_path = launchers.generate_launchers(
                result["name"], result["profile_directory"], result["port"]
            )
            self.refresh()
            self._info(
                "Connection saved",
                f"Launcher scripts generated:\n{bat_path}\n{sh_path}\n\nRun the one for "
                "your OS instead of your normal Chrome icon, then pick this connection "
                "for any class in Add/Edit class.",
            )

    def _on_remove(self) -> None:
        name = self._selected_name()
        if not name:
            self._warn("No selection", "Select a connection to remove first.")
            return
        box = MessageBox("Confirm remove", f"Remove connection '{name}'?", self.window())
        if box.exec():
            settings.remove_connection(name)
            launchers.remove_launchers(name)
            self.refresh()

    def _on_scan(self) -> None:
        found = cdp_probe.scan_for_chrome()
        known_ports = {c["port"] for c in settings.list_connections() if c["backend"] == "cdp"}
        if not found:
            MessageBox(
                "Scan results",
                "No Chrome instances with a debug port open were found on ports "
                f"{cdp_probe.COMMON_PORT_RANGE.start}-{cdp_probe.COMMON_PORT_RANGE.stop - 1}.\n\n"
                "This only applies to 'debug port' connections.",
                self.window(),
            ).exec()
            return
        lines = []
        for f in found:
            tag = " (already configured)" if f["port"] in known_ports else " (not yet configured)"
            lines.append(f"Port {f['port']}: {f.get('Browser', 'unknown')}{tag}")
        MessageBox("Scan results", "Found live Chrome debug ports:\n\n" + "\n".join(lines), self.window()).exec()
        self.refresh()

    def _open_launcher_folder(self) -> None:
        path = str(launchers.LAUNCHER_DIR)
        try:
            if sys.platform == "win32":
                subprocess.Popen(["explorer", path])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception:
            self._info("Launcher folder", path)
