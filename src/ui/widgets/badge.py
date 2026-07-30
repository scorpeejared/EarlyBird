"""A small rounded status pill, e.g. '🟢 Scheduled'."""
from __future__ import annotations

from qfluentwidgets import CaptionLabel

from .. import theme


def make_badge(text: str, fg: str, bg: str, parent=None) -> CaptionLabel:
    """Build a status pill label.

    A factory, not a CaptionLabel subclass: QFluentWidgets label
    constructors dispatch through ``singledispatchmethod`` on
    ``__init__``, which breaks if a subclass adds required arguments.
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
