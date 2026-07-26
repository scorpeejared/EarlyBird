"""In-app progress UI shown while an update downloads and installs.

A MessageBoxBase (same masked-overlay pattern as MeetingDialog/
ConnectionAddEditDialog), but with the Save/Cancel footer replaced: no
buttons at all while busy (there's nothing useful to click, and closing
partway through isn't something we want to make easy), then a single
"Close" button once the process reaches a state that needs
acknowledging (a dev-mode finish, or a failure). On success the app
restarts on its own, so nothing needs to be clicked at all.

Every color here comes from QFluentWidgets components (ProgressBar,
StrongBodyLabel, CaptionLabel, etc.) or from theme.py's semantic
constants, so it follows the app's Light/Dark/Use system setting
automatically - the same as the rest of the app.
"""
from __future__ import annotations

from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    IndeterminateProgressBar,
    MessageBoxBase,
    ProgressBar,
    StrongBodyLabel,
)

from .. import theme


def _format_bytes(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


class UpdateProgressDialog(MessageBoxBase):
    """Shows download/install progress. Call the set_* methods from the
    main thread as the update proceeds; nothing here touches the network
    or filesystem itself."""

    def __init__(self, parent, version_tag: str):
        super().__init__(parent)
        self._busy = True

        self.titleLabel = StrongBodyLabel(f"Updating to {version_tag}", self)
        self.viewLayout.addWidget(self.titleLabel)

        self.stage_label = BodyLabel("Starting update...", self)
        self.stage_label.setWordWrap(True)
        self.viewLayout.addWidget(self.stage_label)

        self.progress_bar = ProgressBar(self)
        self.progress_bar.setRange(0, 100)
        self.viewLayout.addWidget(self.progress_bar)

        self.indeterminate_bar = IndeterminateProgressBar(self, start=False)
        self.indeterminate_bar.hide()
        self.viewLayout.addWidget(self.indeterminate_bar)

        self.detail_label = CaptionLabel("", self)
        self.detail_label.setTextColor("#6B7280", "#9CA3AF")
        self.detail_label.setWordWrap(True)
        self.viewLayout.addWidget(self.detail_label)

        self.widget.setMinimumWidth(420)

        # No Save/Cancel needed while this is running - see module
        # docstring. hideYesButton()/hide() on the footer strip removes
        # both actions until a terminal state re-shows "Close".
        self.hideYesButton()
        self.cancelButton.setText("Close")
        self.buttonGroup.hide()

        self._show_indeterminate()

    # ---------- progress updates (call from the main thread) ----------

    def set_download_progress(self, downloaded: int, total: int) -> None:
        self.stage_label.setText("Downloading update...")
        if total > 0:
            percent = min(100, int(downloaded * 100 / total))
            self._show_determinate(percent)
            self.detail_label.setText(f"{_format_bytes(downloaded)} of {_format_bytes(total)} ({percent}%)")
        else:
            # No Content-Length to compare against - still show something
            # moving rather than a progress bar that's stuck at 0%.
            self._show_indeterminate()
            self.detail_label.setText(f"{_format_bytes(downloaded)} downloaded")

    def set_stage(self, message: str) -> None:
        """A coarse-grained status update, e.g. 'Preparing update...' or
        'Update staged - restarting...' - no byte-level progress to show
        for these steps, so the indeterminate bar takes over."""
        self.stage_label.setText(message)
        self.detail_label.setText("")
        self._show_indeterminate()

    def set_error(self, message: str) -> None:
        self.stage_label.setText("Update failed")
        self.progress_bar.setError(True)
        self.indeterminate_bar.setError(True)
        self.detail_label.setTextColor(theme.DANGER, theme.DANGER)
        self.detail_label.setText(message)
        self._finish()

    def set_finished_dev_mode(self, message: str) -> None:
        self.stage_label.setText("Downloaded (not installed)")
        self.progress_bar.hide()
        self.indeterminate_bar.hide()
        self.indeterminate_bar.stop()
        self.detail_label.setText(message)
        self._finish()

    # ---------- internals ----------

    def _show_determinate(self, percent: int) -> None:
        self.indeterminate_bar.stop()
        self.indeterminate_bar.hide()
        self.progress_bar.show()
        self.progress_bar.setValue(percent)

    def _show_indeterminate(self) -> None:
        self.progress_bar.hide()
        self.indeterminate_bar.show()
        self.indeterminate_bar.start()

    def _finish(self) -> None:
        self._busy = False
        self.buttonGroup.show()

    def reject(self) -> None:  # noqa: N802 (Qt override)
        # Blocks Escape/close while an update is actively downloading or
        # installing; once _finish() has run (error or dev-mode done)
        # this behaves like a normal dialog again.
        if self._busy:
            return
        super().reject()
