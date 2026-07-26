"""
Fluent design tokens for EarlyBird.

QFluentWidgets already supplies typography (Segoe UI Variable), spacing,
rounded corners, and light/dark theming for every stock control, so this
module only fills the handful of gaps the app still needs a shared answer
for: the accent color and the semantic status colors used by the meeting
badges and dashboard stat cards.
"""
from __future__ import annotations

from qfluentwidgets import Theme, setTheme, setThemeColor

# Same indigo used by the previous Tkinter build, so the app keeps its
# visual identity through the framework change.
ACCENT = "#5B5FC7"

SUCCESS = "#0F9D58"
SUCCESS_BG = "#E4F7EC"
SUCCESS_BG_DARK = "#123424"
WARNING = "#B7791F"
WARNING_BG = "#FCF1DC"
WARNING_BG_DARK = "#3A2E12"
DANGER = "#D13438"
DANGER_BG = "#FBE7E7"
DANGER_BG_DARK = "#3A1616"
ACCENT_BG = "#EEF0FC"
ACCENT_BG_DARK = "#23244A"
NEUTRAL = "#6B7280"
NEUTRAL_BG = "#F1F2F6"
NEUTRAL_BG_DARK = "#2B2B2E"

CARD_RADIUS = 8
BADGE_RADIUS = 11

# The default rich-text anchor color Qt picks is a pale blue that reads
# fine on the dark theme but is barely legible on the light theme's
# white cards - so links use this fixed, theme-independent color
# instead of relying on Qt's default link styling.
LINK_COLOR = "#3B5BDB"


def link_html(url: str, text: str) -> str:
    """A hyperlink with an explicit, legible color in both themes -
    use this instead of a bare `<a href=...>` anywhere a link appears
    next to CaptionLabel/other themed text."""
    return f'<a href="{url}" style="color:{LINK_COLOR}; font-weight:600;">{text}</a>'


_MODE_TO_THEME = {
    "light": Theme.LIGHT,
    "dark": Theme.DARK,
    "auto": Theme.AUTO,
}


def apply_theme(mode: str = "light") -> None:
    """Call once at startup, and again whenever the user switches themes."""
    setTheme(_MODE_TO_THEME.get(mode, Theme.LIGHT))
    setThemeColor(ACCENT)
