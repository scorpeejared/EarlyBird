"""
EarlyBird - main GUI application.

A PySide6 + QFluentWidgets interface for managing scheduled Google Meet
links, backed by SQLite, with a background scheduler thread that
auto-joins meetings at their scheduled time and a system tray icon so
the app can run quietly in the background.

This module owns startup/bootstrap only - all scheduling, automation,
storage, and Chrome-integration logic lives in src/scheduler.py,
src/automation.py, src/automation_uia.py, src/storage.py, and
src/settings.py, and is untouched here. The window itself lives in
src/ui/main_window.py.
"""
from __future__ import annotations

import sys
from pathlib import Path

_src_path = Path(__file__).parent / "src"
if str(_src_path) not in sys.path:
    sys.path.insert(0, str(_src_path))
_root_path = Path(__file__).parent
if str(_root_path) not in sys.path:
    sys.path.insert(0, str(_root_path))

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from src import paths, settings, storage
from src.ui.main_window import MainWindow


def main() -> int:
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)  # the tray icon keeps the app alive

    # Make sure the app's storage exists before anything reads from it:
    # data/ + logs/, a settings.json seeded with defaults, and an empty
    # meetings.db with its schema. paths.py decides *where* that lives -
    # notably not inside the PyInstaller temp folder, which is deleted
    # on exit and used to take every saved meeting with it.
    paths.ensure_dirs()
    settings.ensure_data_dir()
    storage.ensure_database()

    window = MainWindow()
    window.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
