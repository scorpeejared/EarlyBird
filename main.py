"""
EarlyBird - application entry point.

A PySide6 + QFluentWidgets interface for managing scheduled Google Meet
links, backed by SQLite, with a background scheduler thread that
auto-joins meetings at their scheduled time and a system tray icon so
the app can run quietly in the background.

This module owns startup only. Everything else lives under src/ - the
window itself is src/ui/main_window.py.
"""
from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

# The project root is already on sys.path (Python adds the running
# script's directory), so `src` imports resolve both from source and
# from a PyInstaller build. Modules inside src/ import each other
# relatively; this is the only file that names them absolutely.
from src import logging_setup, paths, settings, storage
from src.updater import apply_update


def main() -> int:
    # Updater mode: this is a copy of a freshly downloaded build, running from
    # %TEMP% to replace the installed one. Handled before anything else so no
    # database, scheduler or tray icon is ever touched - and before importing
    # MainWindow, which would drag in the whole UI stack it never uses.
    if apply_update.is_updater_invocation(sys.argv[1:]):
        return apply_update.main(sys.argv[1:])

    from src.ui.main_window import MainWindow

    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)  # the tray icon keeps the app alive

    # Create everything the app writes to before anything reads from it:
    # data/ + logs/, a settings.json seeded with defaults, and an empty
    # meetings.db with its schema.
    paths.ensure_dirs()
    logging_setup.configure()
    settings.ensure_data_dir()
    storage.ensure_database()

    # Clear what the last update left in %TEMP% - the runner that performed
    # the swap has finished by now, so this is the only place it can safely go.
    apply_update.cleanup_stale_updates()

    window = MainWindow()
    window.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
