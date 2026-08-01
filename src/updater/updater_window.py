"""
The window the updater shows while it works.

Plain PySide6 rather than the app's fluent widgets, on purpose: this runs
from a temp copy while the real app is shutting down, and its whole job is
to not fail. Nothing here imports the UI stack - the accent below is the
same token as ui/theme.ACCENT, copied rather than imported so a styling
module can never take the updater down with it.

Kept apart from apply_update.py so the update logic itself can be imported
and tested without a GUI.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QPoint, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from .. import settings
from ..logging_setup import get_logger

logger = get_logger()

ACCENT = "#5B5FC7"          # ui/theme.ACCENT
ACCENT_DARK_UI = "#8B8FE8"  # lifted for contrast on a dark card

_LIGHT = {
    "card": "#FFFFFF",
    "text": "#1F2328",
    "muted": "#6B7280",
    "track": "#E7E9F0",
    "chip_bg": "#EEF0FC",
    "chip_text": "#4B4FB5",
    "accent": ACCENT,
    "shadow": QColor(15, 18, 40, 70),
}
_DARK = {
    "card": "#1E1F24",
    "text": "#F2F3F5",
    "muted": "#9AA0AA",
    "track": "#32343B",
    "chip_bg": "#2A2C55",
    "chip_text": "#B9BCF2",
    "accent": ACCENT_DARK_UI,
    "shadow": QColor(0, 0, 0, 160),
}


def _palette() -> dict:
    """Follow the app's own theme setting, falling back to the OS."""
    try:
        mode = settings.get_theme_mode()
    except Exception:  # noqa: BLE001 - styling must never block an update
        mode = "auto"
    if mode == "dark":
        return _DARK
    if mode == "light":
        return _LIGHT
    try:
        return _DARK if QApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark else _LIGHT
    except Exception:  # noqa: BLE001 - older Qt has no colorScheme()
        return _LIGHT


def _app_mark(size: int, colour: str) -> QPixmap:
    """The app's mark, drawn rather than shipped as an asset."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(colour))
    painter.drawEllipse(0, 0, size, size)
    painter.setBrush(QColor(255, 255, 255, 235))
    inner = size * 0.38
    painter.drawEllipse(size * 0.25, size * 0.17, inner, inner)
    painter.setBrush(QColor(colour))
    dot = size * 0.19
    painter.drawEllipse(size * 0.34, size * 0.26, dot, dot)
    painter.end()
    return pixmap


def _format_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


class _ProgressTrack(QWidget):
    """A slim rounded bar: a real fill when there's a percentage, a sweeping
    segment when there isn't. Drawn directly so both states share one look -
    a stylesheet'd QProgressBar renders its busy state quite differently."""

    HEIGHT = 6

    def __init__(self, colours: dict, parent=None):
        super().__init__(parent)
        self._colours = colours
        self._fraction: float | None = None  # None = indeterminate
        self._phase = 0.12  # off-centre at rest, so it never looks parked
        self.setFixedHeight(self.HEIGHT)
        self._timer = QTimer(self)
        self._timer.setInterval(16)  # ~60fps
        self._timer.timeout.connect(self._advance)
        self._timer.start()

    def set_fraction(self, fraction: float | None) -> None:
        self._fraction = None if fraction is None else max(0.0, min(1.0, fraction))
        if self._fraction is None and not self._timer.isActive():
            self._timer.start()
        self.update()

    def _advance(self) -> None:
        if self._fraction is not None:
            self._timer.stop()  # nothing to animate once it's measurable
            return
        self._phase = (self._phase + 0.012) % 1.0
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt override)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)

        radius = self.HEIGHT / 2
        width, height = self.width(), self.height()

        painter.setBrush(QColor(self._colours["track"]))
        painter.drawRoundedRect(0, 0, width, height, radius, radius)

        painter.setBrush(QColor(self._colours["accent"]))
        if self._fraction is not None:
            fill = width * self._fraction
            if fill > 0:
                painter.drawRoundedRect(0, 0, max(fill, self.HEIGHT), height, radius, radius)
        else:
            # Eases back and forth inside the track rather than sweeping in
            # from off-screen - a segment that spends part of its cycle
            # outside the bar reads as "nothing is happening".
            span = width * 0.32
            travel = (width - span) * (0.5 - 0.5 * math.cos(2 * math.pi * self._phase))
            painter.drawRoundedRect(travel, 0, span, height, radius, radius)
        painter.end()


class UpdaterWindow(QWidget):
    """Frameless card: a progress window shouldn't look like a system dialog."""

    def __init__(self, target_version: str = ""):
        super().__init__()
        self._colours = _palette()
        self._drag_from: QPoint | None = None

        self.setWindowTitle("Updating EarlyBird")
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowIcon(QIcon(_app_mark(64, self._colours["accent"])))
        self.setFixedSize(468, 228)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 16, 18, 20)  # room for the shadow

        card = QFrame(self)
        card.setObjectName("card")
        card.setStyleSheet(
            f"#card {{ background: {self._colours['card']}; border-radius: 14px; }}"
        )
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(38)
        shadow.setOffset(0, 8)
        shadow.setColor(self._colours["shadow"])
        card.setGraphicsEffect(shadow)
        outer.addWidget(card)

        body = QVBoxLayout(card)
        body.setContentsMargins(26, 22, 26, 24)
        body.setSpacing(0)

        # --- header: mark, title, version chip ---
        header = QHBoxLayout()
        header.setSpacing(12)
        mark = QLabel()
        mark.setPixmap(_app_mark(34, self._colours["accent"]))
        mark.setFixedSize(34, 34)
        header.addWidget(mark)

        title = QLabel("Updating EarlyBird")
        title.setStyleSheet(
            f"color: {self._colours['text']}; font-size: 16px; font-weight: 600;"
        )
        header.addWidget(title)
        header.addStretch(1)

        if target_version:
            chip = QLabel(target_version)
            chip.setStyleSheet(
                f"color: {self._colours['chip_text']};"
                f"background: {self._colours['chip_bg']};"
                "border-radius: 9px; padding: 3px 10px;"
                "font-size: 11px; font-weight: 600;"
            )
            header.addWidget(chip)
        body.addLayout(header)

        body.addSpacing(20)

        self.status_label = QLabel("Starting...")
        self.status_label.setStyleSheet(
            f"color: {self._colours['text']}; font-size: 13px;"
        )
        body.addWidget(self.status_label)

        body.addSpacing(12)

        self.track = _ProgressTrack(self._colours)
        body.addWidget(self.track)

        body.addSpacing(10)

        footer = QHBoxLayout()
        footer.setSpacing(8)
        self.detail_label = QLabel("")
        self.detail_label.setStyleSheet(
            f"color: {self._colours['muted']}; font-size: 11px;"
        )
        footer.addWidget(self.detail_label)
        footer.addStretch(1)
        self.percent_label = QLabel("")
        self.percent_label.setStyleSheet(
            f"color: {self._colours['muted']}; font-size: 11px; font-weight: 600;"
        )
        footer.addWidget(self.percent_label)
        body.addLayout(footer)

        body.addStretch(1)

        hint = QLabel("EarlyBird will reopen by itself when this finishes.")
        hint.setStyleSheet(f"color: {self._colours['muted']}; font-size: 11px;")
        body.addWidget(hint)

        self._centre_on_screen()

    def _centre_on_screen(self) -> None:
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        area = screen.availableGeometry()
        self.move(area.center().x() - self.width() // 2,
                  area.center().y() - self.height() // 2)

    # Frameless windows don't move themselves; a stuck update shouldn't be
    # stuck on top of whatever it happens to cover.
    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt override)
        if event.button() == Qt.LeftButton:
            self._drag_from = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 (Qt override)
        if self._drag_from is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_from)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 (Qt override)
        self._drag_from = None

    # ---------- updates from the worker ----------

    def set_status(self, message: str) -> None:
        self.status_label.setText(message)
        # Only the download has a measurable size; every other step sweeps.
        if not message.lower().startswith("downloading"):
            self.track.set_fraction(None)
            self.detail_label.setText("")
            self.percent_label.setText("")

    def set_progress(self, downloaded: int, total: int) -> None:
        if total > 0:
            self.track.set_fraction(downloaded / total)
            self.detail_label.setText(
                f"{_format_bytes(downloaded)} of {_format_bytes(total)}")
            self.percent_label.setText(f"{int(downloaded * 100 / total)}%")
        else:
            # No Content-Length: show movement rather than a bar stuck at 0%.
            self.track.set_fraction(None)
            self.detail_label.setText(f"{_format_bytes(downloaded)} downloaded")
            self.percent_label.setText("")


class _Worker(QThread):
    """Runs the update off the GUI thread so the window keeps painting."""

    status = Signal(str)
    progress = Signal(int, int)  # (bytes downloaded, total bytes)
    succeeded = Signal()
    failed = Signal(str)

    def __init__(self, args, run_update: Callable, with_progress: bool, parent=None):
        super().__init__(parent)
        self._args = args
        self._run_update = run_update
        self._with_progress = with_progress

    def run(self) -> None:
        try:
            if self._with_progress:
                self._run_update(self._args, on_status=self.status.emit,
                                 on_progress=self.progress.emit)
            else:
                self._run_update(self._args, on_status=self.status.emit)
            self.succeeded.emit()
        except Exception as e:  # noqa: BLE001 - every failure must reach the user
            logger.exception("Update failed")
            self.failed.emit(str(e))


def run_with_window(
    args,
    run_update: Callable,
    log_path: Path,
    title_version: str = "",
    show_progress: bool = False,
    on_failure: Callable | None = None,
) -> int:
    """Show the window, run the update, report the outcome. Returns an exit code.

    `on_failure` runs before the error is shown - stage 1 uses it to reopen the
    version already installed, since a failure there means nothing was replaced.
    """
    # [sys.argv[0]] rather than sys.argv: Qt must not try to interpret
    # --apply-update and the rest of the updater's own flags.
    app = QApplication([__file__])
    # Quitting is explicit here. Without this, hiding the progress window to
    # show the failure dialog counts as "last window closed", Qt quits, and
    # the modal dialog's event loop dies with it.
    app.setQuitOnLastWindowClosed(False)

    window = UpdaterWindow(title_version)
    colours = window._colours
    if colours is _DARK:
        # QMessageBox is a stock dialog; without this it stays light while
        # the rest of the updater is dark.
        app.setStyleSheet(
            f"QMessageBox {{ background: {colours['card']}; }}"
            f"QMessageBox QLabel {{ color: {colours['text']}; }}"
        )
    window.show()

    outcome: dict[str, str] = {}

    def on_success() -> None:
        outcome["status"] = "ok"
        app.quit()

    def on_worker_failed(message: str) -> None:
        outcome["status"] = "failed"
        outcome["message"] = message
        window.hide()
        reopened = False
        if on_failure is not None:
            try:
                on_failure(args)
                reopened = True
            except Exception:  # noqa: BLE001 - the dialog still has to appear
                logger.exception("Recovery step failed")
        QMessageBox.critical(
            None,
            "Update failed",
            f"EarlyBird could not finish updating:\n\n{message}\n\n"
            + ("Your current version has been reopened and is unaffected."
               if reopened else
               "Your previous version has been restored - reopen EarlyBird to "
               "carry on using it.")
            + f"\n\nDetails: {log_path}",
        )
        app.quit()

    worker = _Worker(args, run_update, with_progress=show_progress)
    worker.status.connect(window.set_status)
    worker.progress.connect(window.set_progress)
    worker.succeeded.connect(on_success)
    worker.failed.connect(on_worker_failed)
    worker.start()

    app.exec()
    worker.wait(5000)
    return 0 if outcome.get("status") == "ok" else 1
