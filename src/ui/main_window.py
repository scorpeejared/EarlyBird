"""
Main application window: navigation shell, tray icon, and the wiring
between the pages and the scheduler/updater services.
"""
from __future__ import annotations

import mimetypes
import threading
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QObject, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QAction, QCloseEvent, QColor, QGuiApplication, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QFileDialog, QMenu, QSystemTrayIcon

from qfluentwidgets import FluentIcon, FluentWindow, InfoBar, InfoBarPosition, MessageBox, NavigationItemPosition

from .. import import_screenshot, settings
from ..logging_setup import get_logger
from ..models import Meeting
from ..scheduler import SchedulerService
from ..storage import MeetingStore
from ..updater import ReleaseInfo, UpdateManager
from ..updater.version import __version__ as APP_VERSION

from .dialogs.ai_setup_dialog import AiSetupDialog, ensure_configured
from .dialogs.import_privacy_dialog import ensure_consent
from .dialogs.import_review_dialog import ImportReviewDialog
from .dialogs.meeting_dialog import MeetingDialog
from .pages.connections_page import ConnectionsPage
from .pages.home_page import HomePage
from .pages.settings_page import SettingsPage
from .theme import apply_theme
from .widgets.update_toast import UpdateToast

APP_TITLE = "EarlyBird 🐦"
UPDATE_REPO_OWNER = "scorpeejared"
UPDATE_REPO_NAME = "EarlyBird"

logger = get_logger()


class _ParseWorker(QThread):
    """Runs one screenshot parse off the GUI thread.

    The request takes seconds over the network, which would freeze the window
    if run inline. Emits (ParseResult | None, error_message).
    """

    done = Signal(object, str)

    def __init__(self, image_bytes: bytes, mime_type: str, parent=None):
        super().__init__(parent)
        self._image_bytes = image_bytes
        self._mime_type = mime_type

    def run(self) -> None:
        try:
            result = import_screenshot.parse_screenshot(self._image_bytes, self._mime_type)
            self.done.emit(result, "")
        except import_screenshot.ParseError as e:
            self.done.emit(None, str(e))
        except Exception as e:  # noqa: BLE001 - a crash here must not kill the window
            logger.warning(f"Unexpected screenshot parse failure: {type(e).__name__}: {e}")
            self.done.emit(None, "Couldn't read this screenshot. Please try again.")
        finally:
            # The screenshot is not kept a moment longer than the request needs
            # it - see the privacy notice.
            self._image_bytes = b""


class _EventBridge(QObject):
    """Relays background-thread callbacks onto the Qt main thread.

    SchedulerService and UpdateManager both fire their callbacks from a
    worker thread; a queued signal connection is what makes it safe to
    touch widgets in response.
    """

    status_changed = Signal(str)
    update_available = Signal(object)
    quit_requested = Signal()


def _build_tray_icon_pixmap() -> QIcon:
    """A simple generated icon so the app doesn't need to ship an asset."""
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(29, 158, 117))
    painter.drawEllipse(4, 4, 56, 56)
    painter.setBrush(QColor(255, 255, 255))
    painter.drawEllipse(20, 14, 24, 24)
    painter.setBrush(QColor(29, 158, 117))
    painter.drawEllipse(26, 20, 12, 12)
    painter.end()
    return QIcon(pixmap)


class MainWindow(FluentWindow):
    def __init__(self):
        super().__init__()
        self._theme_mode = settings.get_theme_mode()
        apply_theme(self._theme_mode)
        self.setWindowTitle(APP_TITLE)
        self.setWindowIcon(_build_tray_icon_pixmap())
        self.setFixedSize(900, 600)
        self.setResizeEnabled(False)
        self.titleBar.maxBtn.hide()
        self._center_on_screen()

        self.store = MeetingStore()
        self._bridge = _EventBridge()
        self._bridge.status_changed.connect(self._on_status_changed)
        self._bridge.update_available.connect(self._show_update_toast)
        self._bridge.quit_requested.connect(self._quit)

        self.scheduler = SchedulerService(self.store, on_status_change=self._bridge.status_changed.emit)
        self.update_manager = UpdateManager(
            repo_owner=UPDATE_REPO_OWNER,
            repo_name=UPDATE_REPO_NAME,
            on_update_available=self._bridge.update_available.emit,
            on_status_change=self._bridge.status_changed.emit,
        )

        self.selected_meeting_id: int | None = None
        self._watching_count = 0
        self._update_toast: UpdateToast | None = None
        self._parse_worker: _ParseWorker | None = None
        self._pending_release: ReleaseInfo | None = None
        self._checking_updates = False
        self.tray_icon: QSystemTrayIcon | None = None
        self._force_quit = False

        self._build_pages()
        self._build_tray_icon()
        self._refresh_all()

        self.scheduler.start()
        self.update_manager.start()

        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._periodic_refresh)
        self._refresh_timer.start(5000)

    # ---------- window geometry ----------

    def _center_on_screen(self) -> None:
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        screen_geometry = screen.availableGeometry()
        frame_geometry = self.frameGeometry()
        frame_geometry.moveCenter(screen_geometry.center())
        self.move(frame_geometry.topLeft())

    # ---------- pages ----------

    def _build_pages(self) -> None:
        self.home_page = HomePage(self)
        self.connections_page = ConnectionsPage(self)
        self.settings_page = SettingsPage(APP_VERSION, self._theme_mode, self)

        self.addSubInterface(self.home_page, FluentIcon.EDUCATION, "Classes", NavigationItemPosition.TOP)
        self.addSubInterface(self.connections_page, FluentIcon.WIFI, "Connections", NavigationItemPosition.TOP)
        self.addSubInterface(self.settings_page, FluentIcon.SETTING, "Settings", NavigationItemPosition.BOTTOM)

        self.home_page.addClicked.connect(self._on_add)
        self.home_page.importClicked.connect(self._on_import_screenshot)
        self.home_page.editClicked.connect(self._on_edit)
        self.home_page.deleteClicked.connect(self._on_delete)
        self.home_page.toggleClicked.connect(self._on_toggle_auto_join)
        self.home_page.meetingSelected.connect(self._on_meeting_selected)
        self.home_page.meetingEditRequested.connect(self._on_edit_id)
        self.home_page.meetingDeleteRequested.connect(self._on_delete_id)
        self.home_page.meetingToggleRequested.connect(self._on_toggle_id)

        self.settings_page.checkForUpdatesClicked.connect(self._check_for_updates_now)
        self.settings_page.updateNowClicked.connect(self._on_inline_update_now)
        self.settings_page.updateLaterClicked.connect(self._on_inline_update_later)
        self.settings_page.themeModeChanged.connect(self._on_theme_mode_changed)
        self.settings_page.configureAiClicked.connect(self._on_configure_ai)

    # ---------- data refresh ----------

    def _refresh_all(self) -> None:
        meetings = sorted(self.store.all(), key=lambda m: m.scheduled_time)
        self.home_page.set_meetings(meetings, self.selected_meeting_id)
        self._watching_count = self.home_page.watching_count()

    def _periodic_refresh(self) -> None:
        self._refresh_all()
        # Don't overwrite "Checking for updates..." or an update prompt
        # with the routine watching-count line.
        if self._checking_updates or self._pending_release is not None:
            return
        stamp = datetime.now().strftime("%I:%M:%S %p").lstrip("0")
        self.settings_page.set_status(f"Watching {self._watching_count} meetings  ·  Last checked {stamp}")

    def _selected_meeting(self) -> Meeting | None:
        if self.selected_meeting_id is None:
            return None
        return self.store.get(self.selected_meeting_id)

    def _on_meeting_selected(self, meeting_id: int) -> None:
        self.selected_meeting_id = meeting_id
        self._refresh_all()

    def _on_theme_mode_changed(self, mode: str) -> None:
        if mode == self._theme_mode:
            return
        self._theme_mode = mode
        settings.save_theme_mode(mode)
        apply_theme(mode)
        # Meeting-card badges and the day picker bake their light/dark
        # colors in at build time, so they need rebuilding to re-theme.
        self._refresh_all()

    # ---------- toasts ----------

    def _notify(self, kind: str, title: str, content: str) -> None:
        factory = {
            "success": InfoBar.success, "warning": InfoBar.warning,
            "error": InfoBar.error, "info": InfoBar.info,
        }[kind]
        factory(
            title=title, content=content, orient=Qt.Horizontal, isClosable=True,
            position=InfoBarPosition.TOP_RIGHT, duration=4000, parent=self,
        )

    # ---------- class CRUD ----------

    def _on_add(self) -> None:
        dlg = MeetingDialog(self)
        if dlg.exec() and dlg.result:
            new_id = self.store.add(dlg.result)
            self.selected_meeting_id = new_id
            self._refresh_all()
            self._notify("success", "Class added", f"'{dlg.result.title}' was scheduled.")

    # ---------- import from screenshot ----------

    def _on_configure_ai(self) -> None:
        if AiSetupDialog(self).exec():
            self.settings_page.refresh_ai_status()
            self._notify("success", "AI updated", "Screenshot import will use the new provider.")

    @staticmethod
    def _image_to_png_bytes(image) -> bytes:
        """Serialise a clipboard QImage to PNG bytes, in memory only."""
        buffer = QBuffer(QByteArray())
        buffer.open(QBuffer.WriteOnly)
        image.save(buffer, "PNG")
        return bytes(buffer.data())

    def _pick_screenshot(self) -> tuple[bytes, str] | None:
        """Get an image from the clipboard or a file. None if cancelled."""
        clipboard_image = QGuiApplication.clipboard().image()
        if not clipboard_image.isNull():
            box = MessageBox(
                "Use the image you copied?",
                "There's an image on your clipboard. Use that, or pick a file instead.",
                self,
            )
            box.yesButton.setText("Use clipboard image")
            box.cancelButton.setText("Choose a file...")
            if box.exec():
                return self._image_to_png_bytes(clipboard_image), "image/png"

        path, _selected = QFileDialog.getOpenFileName(
            self, "Choose a schedule screenshot", "",
            "Images (*.png *.jpg *.jpeg *.webp *.gif)",
        )
        if not path:
            return None
        try:
            data = Path(path).read_bytes()
        except OSError as e:
            self._notify("error", "Couldn't open that file", str(e))
            return None

        mime_type = mimetypes.guess_type(path)[0] or "image/png"
        if mime_type not in ("image/png", "image/jpeg", "image/webp", "image/gif"):
            mime_type = "image/png"
        return data, mime_type

    def _on_import_screenshot(self) -> None:
        """Screenshot -> draft rows -> review -> save.

        The parse runs on a worker thread; everything that touches the
        database happens back here, only after the user confirms.
        """
        if self._parse_worker is not None and self._parse_worker.isRunning():
            self._notify("warning", "Still reading", "One screenshot is already being read.")
            return
        # Setup first, because the privacy notice has to name the provider the
        # user actually picked. Both come before the file dialog, so nobody
        # hunts down a screenshot only to hit a wall.
        if not ensure_configured(self):
            return
        if not ensure_consent(self):
            return

        picked = self._pick_screenshot()
        if picked is None:
            return
        image_bytes, mime_type = picked

        self._notify("info", "Reading screenshot", "Sending the image to Gemini. This takes a few seconds.")

        worker = _ParseWorker(image_bytes, mime_type)
        worker.done.connect(self._on_parse_finished)
        worker.finished.connect(lambda: setattr(self, "_parse_worker", None))
        self._parse_worker = worker
        worker.start()
        # Local reference dropped now that the worker owns the only copy.
        del image_bytes, picked

    def _on_parse_finished(self, parsed, error_message: str) -> None:
        if error_message:
            self._notify("error", "Couldn't read the screenshot", error_message)
            return

        if not parsed.found_schedule:
            self._notify(
                "warning", "No schedule found",
                parsed.reason or "Couldn't find a schedule table in this image.",
            )
            return

        if parsed.dropped:
            # Dropped rows are reported, never silently discarded.
            self._notify(
                "warning", "Some rows were unreadable",
                f"{parsed.dropped} row(s) couldn't be read and aren't shown. "
                "Add those by hand if you need them.",
            )

        dlg = ImportReviewDialog(self, parsed)
        if not dlg.exec() or not dlg.result:
            return

        # Reuses the same MeetingStore.add() path as the Add dialog, so
        # imported classes are ordinary meetings from here on.
        last_id = None
        for meeting in dlg.result:
            last_id = self.store.add(meeting)
        if last_id is not None:
            self.selected_meeting_id = last_id
        self._refresh_all()
        count = len(dlg.result)
        self._notify(
            "success", "Classes imported",
            f"{count} {'class' if count == 1 else 'classes'} added from the screenshot.",
        )

    def _on_edit(self) -> None:
        m = self._selected_meeting()
        if not m:
            self._notify("warning", "No selection", "Select a class to edit first.")
            return
        self._edit_meeting(m)

    def _on_edit_id(self, meeting_id: int) -> None:
        self.selected_meeting_id = meeting_id
        m = self.store.get(meeting_id)
        if m:
            self._edit_meeting(m)

    def _edit_meeting(self, m: Meeting) -> None:
        dlg = MeetingDialog(self, meeting=m)
        if dlg.exec() and dlg.result:
            self.store.update(dlg.result)
            self._refresh_all()
            self._notify("success", "Class updated", f"'{dlg.result.title}' was saved.")

    def _on_delete(self) -> None:
        m = self._selected_meeting()
        if not m:
            self._notify("warning", "No selection", "Select a class to delete first.")
            return
        self._delete_meeting(m)

    def _on_delete_id(self, meeting_id: int) -> None:
        m = self.store.get(meeting_id)
        if m:
            self._delete_meeting(m)

    def _delete_meeting(self, m: Meeting) -> None:
        box = MessageBox("Confirm delete", f"Delete '{m.title}'?", self)
        if box.exec():
            self.store.delete(m.id)
            self.selected_meeting_id = None
            self._refresh_all()
            self._notify("success", "Class deleted", f"'{m.title}' was removed.")

    def _on_toggle_auto_join(self) -> None:
        m = self._selected_meeting()
        if not m:
            self._notify("warning", "No selection", "Select a class first.")
            return
        self._toggle_meeting(m)

    def _on_toggle_id(self, meeting_id: int) -> None:
        m = self.store.get(meeting_id)
        if m:
            self._toggle_meeting(m)

    def _toggle_meeting(self, m: Meeting) -> None:
        m.auto_join = not m.auto_join
        self.store.update(m)
        self._refresh_all()
        state = "enabled" if m.auto_join else "disabled"
        self._notify("success", "Auto-join updated", f"Auto-join {state} for '{m.title}'.")

    # ---------- scheduler status ----------

    def _on_status_changed(self, message: str) -> None:
        self.settings_page.set_status(message)
        if message.startswith("Joined"):
            self._notify("success", "Joined class", message)
        elif message.startswith("Failed to join"):
            self._notify("error", "Join failed", message)

    # ---------- updates ----------

    def _check_for_updates_now(self) -> None:
        self._checking_updates = True
        self.settings_page.set_status("Checking for updates...")

        def worker():
            try:
                # force=True: a manual click gets a real answer even if
                # this version was previously dismissed with "Later".
                self.update_manager.check_for_updates(force=True)
            finally:
                self._checking_updates = False

        threading.Thread(target=worker, daemon=True).start()

    def _show_update_toast(self, release: ReleaseInfo) -> None:
        self._pending_release = release
        self.settings_page.show_update_available(release.tag, release.html_url)

        if self._update_toast and self._update_toast.isVisible():
            return
        self._update_toast = UpdateToast(
            self,
            current_version=APP_VERSION,
            release=release,
            on_restart=lambda: self._start_restart_and_update(release),
            on_later=self._on_inline_update_later,
        )
        self._update_toast.show()

    def _on_inline_update_now(self) -> None:
        """'Update now' on the Settings page - same action as the toast."""
        if self._pending_release:
            self._start_restart_and_update(self._pending_release)

    def _on_inline_update_later(self) -> None:
        """'Later', from either the Settings page or the toast: dismiss
        this version and put both back to their idle state."""
        if self._pending_release:
            self.update_manager.dismiss(self._pending_release)
        self._pending_release = None
        self.settings_page.clear_update_available()
        if self._update_toast:
            self._update_toast.close()

    def _start_restart_and_update(self, release: ReleaseInfo) -> None:
        """Hand the update to the updater and quit.

        Downloading and installing both belong to the updater now, so there is
        nothing to show progress for here: this only starts it (which returns
        at once) and then runs the normal quit sequence. The updater has its
        own window and waits on this process's PID.
        """
        self.settings_page.clear_update_available()
        if self._update_toast:
            self._update_toast.close()

        try:
            started = self.update_manager.start_update(release)
        except Exception as e:
            logger.exception("Could not start the updater")
            self._notify("error", "Update failed", str(e))
            return
        finally:
            self._pending_release = None

        if started:
            self._force_quit = True
            self._quit()
        else:
            self._notify(
                "warning", "Not available from source",
                "Self-update only works in a packaged build.",
            )

    # ---------- tray / lifecycle ----------

    def _build_tray_icon(self) -> None:
        self.tray_icon = QSystemTrayIcon(_build_tray_icon_pixmap(), self)
        self.tray_icon.setToolTip(APP_TITLE)
        menu = QMenu()
        open_action = QAction("Open EarlyBird", self)
        open_action.triggered.connect(self._restore_from_tray)
        quit_action = QAction("Quit", self)
        quit_action.triggered.connect(self._quit)
        menu.addAction(open_action)
        menu.addAction(quit_action)
        self.tray_icon.setContextMenu(menu)
        self.tray_icon.activated.connect(
            lambda reason: self._restore_from_tray()
            if reason == QSystemTrayIcon.ActivationReason.Trigger else None
        )

    def _minimize_to_tray(self) -> None:
        self.hide()
        if self.tray_icon:
            self.tray_icon.show()

    def _restore_from_tray(self) -> None:
        self.showNormal()
        self.activateWindow()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._force_quit:
            event.accept()
            return
        box = MessageBox(
            "Close or minimize?",
            "Minimize to tray and keep auto-joining in the background? "
            "(Choose 'Quit' to close the app entirely.)",
            self,
        )
        box.yesButton.setText("Minimize")
        box.cancelButton.setText("Quit")
        if box.exec():
            self._minimize_to_tray()
            event.ignore()
        else:
            self._quit()
            event.accept()

    def _quit(self) -> None:
        self._force_quit = True
        self.scheduler.stop()
        self.update_manager.stop()
        if self.tray_icon:
            self.tray_icon.hide()
        QApplication.instance().quit()
