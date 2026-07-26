"""A small rounded status pill, e.g. '🟢 Scheduled'."""
from __future__ import annotations

from qfluentwidgets import CaptionLabel

from .. import theme


def make_badge(text: str, fg: str, bg: str, parent=None) -> CaptionLabel:
    """Build a status pill label.

    A plain factory function rather than a CaptionLabel subclass: several
    QFluentWidgets label constructors use ``singledispatchmethod`` on
    ``__init__``, which re-dispatches through ``self.__init__`` internally -
    subclassing and overriding ``__init__`` with extra required
    parameters breaks that dispatch, so composition is used instead.
    """
    label = CaptionLabel(text, parent)
    label.setStyleSheet(
        f"""
        CaptionLabel {{
            color: {fg};
            background-color: {bg};
            border-radius: {theme.BADGE_RADIUS}px;
            padding: 3px 10px;
            font-weight: 600;
        }}
        """
    )
    return label
