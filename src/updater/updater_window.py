"""
The small window the updater shows while it works.

Deliberately plain PySide6 rather than the app's fluent widgets: this runs
while the real app is closing, from a temp copy, and its whole job is to not
fail. Fewer imports, fewer ways to break.

Kept apart from apply_update.py so the update logic itself can be imported and
tested without a GUI.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QMessageBox,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from ..logging_setup import get_logger

logger = get_logger()


class _Worker(QThread):
    """Runs the update off the GUI thread so the window keeps painting."""

    status = Signal(str)
    succeeded = Signal()
    failed = Signal(str)

    def __init__(self, args, run_update: Callable, parent=None):
        super().__init__(parent)
        self._args = args
        self._run_update = run_update

    def run(self) -> None:
        try:
            self._run_update(self._args, on_status=self.status.emit)
            self.succeeded.emit()
        except Exception as e:  # noqa: BLE001 - every failure must reach the user
            logger.exception("Update failed")
            self.failed.emit(str(e))


class UpdaterWindow(QWidget):
    def __init__(self, target_version: str = ""):
        super().__init__()
        self.setWindowTitle("Updating EarlyBird")
        self.setFixedSize(420, 130)
        self.setWindowFlag(Qt.WindowCloseButtonHint, False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)

        heading = QLabel(f"Updating EarlyBird{f' to {target_version}' if target_version else ''}")
        heading.setStyleSheet("font-size: 14px; font-weight: 600;")
        layout.addWidget(heading)

        self.status_label = QLabel("Starting...")
        self.status_label.setStyleSheet("color: #6B7280;")
        layout.addWidget(self.status_label)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)  # indeterminate: the steps aren't measurable
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(6)
        layout.addWidget(self.progress)

    def set_status(self, message: str) -> None:
        self.status_label.setText(message)


def run_with_window(args, run_update: Callable, log_path: Path) -> int:
    """Show the window, run the update, report the outcome. Returns an exit code."""
    # [sys.argv[0]] rather than sys.argv: Qt must not try to interpret
    # --apply-update and the rest of the updater's own flags.
    app = QApplication([__file__])

    window = UpdaterWindow()
    window.show()

    outcome: dict[str, str] = {}

    def on_success() -> None:
        outcome["status"] = "ok"
        app.quit()

    def on_failure(message: str) -> None:
        outcome["status"] = "failed"
        outcome["message"] = message
        window.hide()
        QMessageBox.critical(
            None,
            "Update failed",
            f"EarlyBird could not finish updating:\n\n{message}\n\n"
            "Your previous version has been restored - reopen EarlyBird to "
            f"carry on using it.\n\nDetails: {log_path}",
        )
        app.quit()

    worker = _Worker(args, run_update)
    worker.status.connect(window.set_status)
    worker.succeeded.connect(on_success)
    worker.failed.connect(on_failure)
    worker.start()

    app.exec()
    worker.wait(5000)
    return 0 if outcome.get("status") == "ok" else 1
