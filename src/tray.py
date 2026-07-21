"""
System tray icon so the app can keep auto-joining classes while minimized.
"""
from PIL import Image, ImageDraw
import pystray


def _build_icon_image() -> Image.Image:
    """A simple generated icon (green circle with a white play-ish mark)
    so the app doesn't depend on shipping a separate .ico/.png asset."""
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse((4, 4, 60, 60), fill=(29, 158, 117, 255))  # teal circle
    draw.rectangle((26, 18, 34, 46), fill=(255, 255, 255, 255))  # simple glyph
    draw.ellipse((20, 14, 44, 38), fill=(255, 255, 255, 255))
    draw.ellipse((26, 20, 38, 32), fill=(29, 158, 117, 255))
    return img


def build_tray_icon(restore_callback, quit_callback) -> pystray.Icon:
    menu = pystray.Menu(
        pystray.MenuItem("Open EarlyBird", lambda: restore_callback()),
        pystray.MenuItem("Quit", lambda: quit_callback()),
    )
    return pystray.Icon("meet_auto_joiner", _build_icon_image(), "EarlyBird", menu)
