"""
EarlyBird - main GUI application.

A Tkinter/ttk interface for managing scheduled Google Meet links, backed
by SQLite, with a background scheduler thread that auto-joins meetings at
their scheduled time and a system tray icon so the app can run quietly in
the background.

This module owns presentation only - all scheduling, automation, storage,
and Chrome-integration logic lives in scheduler.py / automation.py /
automation_uia.py / storage.py / settings.py and is untouched here.
"""
from __future__ import annotations

import sys

if sys.platform == "win32":
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception: 
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


import sys
from pathlib import Path
_src_path = Path(__file__).parent / "src"
if str(_src_path) not in sys.path:
    sys.path.insert(0, str(_src_path))

import threading
import tkinter as tk
from datetime import datetime, date, time as dtime
from tkinter import ttk, messagebox

from src.models import Meeting
from src.storage import MeetingStore
from src.scheduler import SchedulerService
from src import settings
from src import recurrence


APP_TITLE = "EarlyBird 🐦"

# ---------------------------------------------------------------------------
# Design tokens - the whole visual language lives here. ttk widgets pick
# most of this up automatically via App._setup_style() (which configures
# the global theme, cascading to every dialog); raw tk widgets (Canvas-based
# buttons/badges, card frames) reference these dicts directly.
# ---------------------------------------------------------------------------
COLORS = {
    "bg": "#F5F7FB",
    "surface": "#FFFFFF",
    "primary": "#5865F2",
    "primary_hover": "#4752C4",
    "primary_soft": "#ECEEFD",
    "success": "#22C55E",
    "success_bg": "#E9FBF0",
    "warning": "#F59E0B",
    "warning_bg": "#FEF6E7",
    "danger": "#EF4444",
    "danger_bg": "#FDECEC",
    "text": "#1F2937",
    "text_secondary": "#6B7280",
    "border": "#E5E7EB",
}

FONTS = {
    "title": ("Segoe UI", 18, "bold"),
    "subtitle": ("Segoe UI", 10),
    "heading": ("Segoe UI", 12, "bold"),
    "body": ("Segoe UI", 10),
    "body_bold": ("Segoe UI", 10, "bold"),
    "small": ("Segoe UI", 9),
    "small_bold": ("Segoe UI", 9, "bold"),
    "button": ("Segoe UI", 10),
    "button_bold": ("Segoe UI", 10, "bold"),
    "stat_number": ("Segoe UI", 24, "bold"),
    "empty_icon": ("Segoe UI", 40),
}


# Reusable UI building blocks

def _rounded_points(x1, y1, x2, y2, r):
    """Point list for a rounded-rectangle polygon - ttk can't draw rounded
    corners at all, so canvas polygons are how every "card" and "button"
    edge in this app gets its rounding."""
    r = min(r, (x2 - x1) / 2, (y2 - y1) / 2)
    return [
        x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
        x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
        x1, y2, x1, y2 - r, x1, y1 + r, x1, y1,
    ]


class RoundedButton(tk.Canvas):
    """A small canvas button with real rounded corners, hover/press
    feedback, and a disabled state - fills the gap ttk leaves here, since
    ttk buttons render as flat OS rectangles with no rounding at all."""

    _PALETTES = {
        "primary": {
            "bg": COLORS["primary"], "bg_hover": COLORS["primary_hover"],
            "fg": "#FFFFFF", "border": None, "font": FONTS["button_bold"],
        },
        "secondary": {
            "bg": COLORS["surface"], "bg_hover": COLORS["bg"],
            "fg": COLORS["text"], "border": COLORS["border"], "font": FONTS["button"],
        },
        "danger": {
            "bg": COLORS["danger_bg"], "bg_hover": "#FBDCDA",
            "fg": COLORS["danger"], "border": None, "font": FONTS["button_bold"],
        },
        "ghost": {
            "bg": None, "bg_hover": COLORS["border"],
            "fg": COLORS["text_secondary"], "border": None, "font": FONTS["button"],
        },
    }

    def __init__(self, parent, text, command=None, kind="secondary",
                 width=None, height=34, radius=8, bg=None, padding=16):
        self.command = command
        self.kind = kind
        self.text = text
        self.radius = radius
        self.enabled = True
        self._hover = False
        self._pressed = False
        pal = dict(self._PALETTES[kind])
        if pal["bg"] is None:
            pal["bg"] = bg or (parent.cget("bg") if hasattr(parent, "cget") else COLORS["bg"])
        self.pal = pal
        self.font = pal["font"]

        tmp = tk.Label(parent, text=text, font=self.font)
        tmp.update_idletasks()
        text_w = tmp.winfo_reqwidth()
        tmp.destroy()
        self.width = width or (text_w + padding * 2)
        self.height = height

        outer_bg = bg or (parent.cget("bg") if hasattr(parent, "cget") else COLORS["bg"])
        super().__init__(parent, width=self.width, height=self.height,
                          bg=outer_bg, highlightthickness=0, bd=0)

        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)
        self._redraw()

    def _redraw(self):
        self.delete("all")
        pal = self.pal
        if not self.enabled:
            fill = COLORS["border"]
            fg = COLORS["text_secondary"]
            outline = ""
        elif self._pressed or self._hover:
            fill = pal["bg_hover"]
            fg = pal["fg"]
            outline = pal["border"] or fill
        else:
            fill = pal["bg"]
            fg = pal["fg"]
            outline = pal["border"] or fill
        pts = _rounded_points(1, 1, self.width - 1, self.height - 1, self.radius)
        self.create_polygon(pts, smooth=True, fill=fill, outline=outline)
        self.create_text(self.width / 2, self.height / 2, text=self.text, fill=fg, font=self.font)

    def _on_enter(self, _e=None):
        if self.enabled:
            self._hover = True
            self.configure(cursor="hand2")
            self._redraw()

    def _on_leave(self, _e=None):
        self._hover = False
        self._pressed = False
        self.configure(cursor="")
        self._redraw()

    def _on_press(self, _e=None):
        if self.enabled:
            self._pressed = True
            self._redraw()

    def _on_release(self, _e=None):
        if self.enabled and self._pressed:
            self._pressed = False
            self._redraw()
            if self.command:
                self.command()
        else:
            self._pressed = False
            self._redraw()

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = enabled
        self._redraw()


def make_badge(parent, text, fg, bg_soft, bg_behind=None):
    """A small rounded status pill, e.g. '🟢 Scheduled'."""
    font = FONTS["small_bold"]
    tmp = tk.Label(parent, text=text, font=font)
    tmp.update_idletasks()
    w = tmp.winfo_reqwidth() + 20
    h = 22
    tmp.destroy()
    outer_bg = bg_behind or (parent.cget("bg") if hasattr(parent, "cget") else COLORS["surface"])
    c = tk.Canvas(parent, width=w, height=h, bg=outer_bg, highlightthickness=0, bd=0)
    pts = _rounded_points(1, 1, w - 1, h - 1, h / 2)
    c.create_polygon(pts, smooth=True, fill=bg_soft, outline=bg_soft)
    c.create_text(w / 2, h / 2, text=text, fill=fg, font=font)
    return c


class Card(tk.Frame):
    """A flat white 'card' surface with a thin rounded-look border - the
    basic visual container used for the dashboard stats and meeting rows."""

    def __init__(self, parent, **kwargs):
        bg = kwargs.pop("bg", COLORS["surface"])
        super().__init__(parent, bg=bg, highlightbackground=COLORS["border"],
                          highlightthickness=1, bd=0, **kwargs)


class ScrollableFrame(tk.Frame):
    """A vertically scrollable container - used for the meeting list, since
    a growing schedule shouldn't force the whole window to grow with it."""

    def __init__(self, parent, bg=None):
        bg = bg or COLORS["bg"]
        super().__init__(parent, bg=bg)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.body = tk.Frame(self.canvas, bg=bg)
        self._window = self.canvas.create_window((0, 0), window=self.body, anchor="nw")

        self.body.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfig(self._window, width=e.width))
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")

        self.canvas.bind("<Enter>", self._bind_wheel)
        self.canvas.bind("<Leave>", self._unbind_wheel)

    def _bind_wheel(self, _e=None):
        self.canvas.bind_all("<MouseWheel>", self._on_wheel)

    def _unbind_wheel(self, _e=None):
        self.canvas.unbind_all("<MouseWheel>")

    def _on_wheel(self, event):
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def clear(self):
        for child in self.body.winfo_children():
            child.destroy()


class DayOfWeekPicker(tk.Frame):
    """Apple Clock–style circular day-of-week toggles (Sunday first)."""

    DIAMETER = 36

    def __init__(self, parent, bg=None, initial_days: frozenset[int] | None = None):
        bg = bg or COLORS["bg"]
        super().__init__(parent, bg=bg)
        self._selected: set[int] = set(initial_days or ())
        self._canvases: dict[int, tk.Canvas] = {}
        self._summary_var = tk.StringVar(value=recurrence.format_repeat_label(frozenset(self._selected)))

        row = tk.Frame(self, bg=bg)
        row.pack(anchor="w")
        for weekday, letter in recurrence.APPLE_DAY_ORDER:
            c = tk.Canvas(
                row, width=self.DIAMETER, height=self.DIAMETER,
                bg=bg, highlightthickness=0, bd=0, cursor="hand2",
            )
            c.pack(side="left", padx=3)
            c.bind("<Button-1>", lambda _e, d=weekday: self._toggle(d))
            self._canvases[weekday] = c

        presets = tk.Frame(self, bg=bg)
        presets.pack(anchor="w", pady=(10, 0))
        for label, days in [("Weekdays", recurrence.WEEKDAYS), ("Every day", recurrence.ALL_DAYS)]:
            RoundedButton(
                presets, label, command=lambda d=days: self.set_days(d),
                kind="secondary", height=28, padding=12, bg=bg,
            ).pack(side="left", padx=(0, 6))

        tk.Label(
            self, textvariable=self._summary_var, bg=bg,
            fg=COLORS["text_secondary"], font=FONTS["small"],
        ).pack(anchor="w", pady=(8, 0))

        self._redraw_all()

    def _toggle(self, weekday: int) -> None:
        if weekday in self._selected:
            self._selected.discard(weekday)
        else:
            self._selected.add(weekday)
        self._redraw_all()

    def _redraw_day(self, weekday: int) -> None:
        c = self._canvases[weekday]
        c.delete("all")
        selected = weekday in self._selected
        letter = next(lbl for wd, lbl in recurrence.APPLE_DAY_ORDER if wd == weekday)
        d = self.DIAMETER
        pad = 2
        if selected:
            fill = COLORS["primary"]
            fg = "#FFFFFF"
            outline = COLORS["primary"]
        else:
            fill = COLORS["surface"]
            fg = COLORS["text_secondary"]
            outline = COLORS["border"]
        pts = _rounded_points(pad, pad, d - pad, d - pad, (d - pad * 2) / 2)
        c.create_polygon(pts, smooth=True, fill=fill, outline=outline)
        c.create_text(d / 2, d / 2, text=letter, fill=fg, font=FONTS["small_bold"])

    def _redraw_all(self) -> None:
        for weekday in self._canvases:
            self._redraw_day(weekday)
        self._summary_var.set(recurrence.format_repeat_label(frozenset(self._selected)))

    def get_days(self) -> frozenset[int]:
        return frozenset(self._selected)

    def set_days(self, days: frozenset[int] | set[int]) -> None:
        self._selected = set(days)
        self._redraw_all()


# Dialogs

class MeetingDialog(tk.Toplevel):
    """Add/Edit dialog for a single meeting."""

    def __init__(self, parent, meeting: Meeting | None = None):
        super().__init__(parent)
        self.configure(bg=COLORS["bg"])
        self.title("Edit class" if meeting else "Add class")
        self.resizable(False, False)
        self.result: Meeting | None = None
        self._meeting = meeting
        self.grab_set()

        pad = {"padx": 20, "pady": 8}
        outer = tk.Frame(self, bg=COLORS["bg"])
        outer.pack(fill="both", expand=True, padx=4, pady=4)

        heading = "✏️  Edit class" if meeting else "➕  Add a new class"
        tk.Label(outer, text=heading, bg=COLORS["bg"], fg=COLORS["text"], font=FONTS["heading"]).grid(
            row=0, column=0, columnspan=4, sticky="w", padx=20, pady=(18, 10)
        )

        ttk.Label(outer, text="Title").grid(row=1, column=0, sticky="w", **pad)
        self.title_var = tk.StringVar(value=meeting.title if meeting else "")
        ttk.Entry(outer, textvariable=self.title_var, width=42).grid(row=1, column=1, columnspan=3, **pad)

        ttk.Label(outer, text="Google Meet link").grid(row=2, column=0, sticky="w", **pad)
        self.link_var = tk.StringVar(value=meeting.link if meeting else "")
        ttk.Entry(outer, textvariable=self.link_var, width=42).grid(row=2, column=1, columnspan=3, **pad)

        default_dt = meeting.scheduled_time if meeting else datetime.now()
        is_repeat = recurrence.is_recurring(meeting) if meeting else False
        initial_days = recurrence.parse_days(meeting.recurring_days) if meeting else frozenset()

        self.date_label = ttk.Label(outer, text="Date (YYYY-MM-DD)")
        self.date_label.grid(row=3, column=0, sticky="w", **pad)
        self.date_var = tk.StringVar(value=default_dt.strftime("%Y-%m-%d"))
        self.date_entry = ttk.Entry(outer, textvariable=self.date_var, width=15)
        self.date_entry.grid(row=3, column=1, sticky="w", **pad)

        ttk.Label(outer, text="Time (HH:MM, 24h)").grid(row=3, column=2, sticky="w", **pad)
        self.time_var = tk.StringVar(value=default_dt.strftime("%H:%M"))
        ttk.Entry(outer, textvariable=self.time_var, width=10).grid(row=3, column=3, sticky="w", **pad)

        ttk.Separator(outer, orient="horizontal").grid(row=4, column=0, columnspan=4, sticky="ew", padx=20, pady=(8, 8))

        self.auto_join_var = tk.BooleanVar(value=meeting.auto_join if meeting else True)
        ttk.Checkbutton(outer, text="Auto-join at scheduled time", variable=self.auto_join_var).grid(
            row=5, column=0, columnspan=2, sticky="w", **pad
        )

        self.mic_var = tk.BooleanVar(value=meeting.mute_mic if meeting else True)
        ttk.Checkbutton(outer, text="Mute microphone on join", variable=self.mic_var).grid(
            row=6, column=0, columnspan=2, sticky="w", **pad
        )
        self.cam_var = tk.BooleanVar(value=meeting.mute_camera if meeting else True)
        ttk.Checkbutton(outer, text="Turn off camera on join", variable=self.cam_var).grid(
            row=6, column=2, columnspan=2, sticky="w", **pad
        )

        ttk.Label(outer, text="Join early (minutes)").grid(row=7, column=0, sticky="w", **pad)
        self.join_early_var = tk.StringVar(
            value=str(meeting.join_early_minutes if meeting else 0)
        )
        ttk.Spinbox(
            outer, from_=0, to=60, increment=1, textvariable=self.join_early_var, width=6,
        ).grid(row=7, column=1, sticky="w", **pad)
        ttk.Label(
            outer, text="0 = join exactly at the scheduled time", foreground="#888888",
        ).grid(row=7, column=2, columnspan=2, sticky="w", **pad)

        self.repeat_var = tk.BooleanVar(value=is_repeat)
        ttk.Checkbutton(outer, text="Repeat", variable=self.repeat_var, command=self._toggle_repeat).grid(
            row=8, column=0, sticky="w", **pad
        )

        self.repeat_frame = tk.Frame(outer, bg=COLORS["bg"])
        self.repeat_frame.grid(row=9, column=0, columnspan=4, sticky="w", padx=20, pady=(0, 4))
        self.day_picker = DayOfWeekPicker(self.repeat_frame, bg=COLORS["bg"], initial_days=initial_days)
        self.day_picker.pack(anchor="w")

        ttk.Label(outer, text="Join using").grid(row=10, column=0, sticky="w", **pad)
        names = settings.connection_names()
        current_name = (meeting.chrome_connection if meeting and meeting.chrome_connection else None)
        default_label = current_name if current_name in names else settings.ISOLATED_PROFILE_LABEL
        self.connection_var = tk.StringVar(value=default_label)
        ttk.Combobox(
            outer, textvariable=self.connection_var, values=names, width=36, state="readonly",
        ).grid(row=10, column=1, columnspan=3, sticky="w", **pad)

        btns = tk.Frame(outer, bg=COLORS["bg"])
        btns.grid(row=11, column=0, columnspan=4, pady=(14, 18))
        RoundedButton(btns, "Save", command=self._on_save, kind="primary", bg=COLORS["bg"]).pack(side="left", padx=6)
        RoundedButton(btns, "Cancel", command=self.destroy, kind="secondary", bg=COLORS["bg"]).pack(side="left", padx=6)

        self._toggle_repeat()

    def _toggle_repeat(self) -> None:
        repeating = self.repeat_var.get()
        if repeating:
            self.repeat_frame.grid()
            self.date_label.configure(text="Starting from (YYYY-MM-DD)")
        else:
            self.repeat_frame.grid_remove()
            self.date_label.configure(text="Date (YYYY-MM-DD)")

    def _on_save(self) -> None:
        title = self.title_var.get().strip()
        link = self.link_var.get().strip()
        if not title or not link:
            messagebox.showerror("Missing info", "Title and Meet link are required.", parent=self)
            return
        try:
            y, mo, d = (int(x) for x in self.date_var.get().split("-"))
            h, mi = (int(x) for x in self.time_var.get().split(":"))
            scheduled = datetime.combine(date(y, mo, d), dtime(h, mi))
        except ValueError:
            messagebox.showerror(
                "Invalid date/time",
                "Use YYYY-MM-DD for date and HH:MM (24h) for time.",
                parent=self,
            )
            return

        repeating = self.repeat_var.get()
        if repeating:
            days = self.day_picker.get_days()
            if not days:
                messagebox.showerror(
                    "No repeat days",
                    "Select at least one day of the week, or turn off Repeat.",
                    parent=self,
                )
                return
            recurring = recurrence.RECURRING_WEEKLY
            recurring_days = recurrence.serialize_days(days)
        else:
            recurring = recurrence.RECURRING_NONE
            recurring_days = ""

        try:
            join_early_minutes = int(self.join_early_var.get())
            if join_early_minutes < 0:
                raise ValueError
        except ValueError:
            messagebox.showerror(
                "Invalid join early value",
                "Join early must be a whole number of minutes (0 or more).",
                parent=self,
            )
            return

        chosen = self.connection_var.get()
        chrome_connection = "" if chosen == settings.ISOLATED_PROFILE_LABEL else chosen

        self.result = Meeting(
            id=self._meeting.id if self._meeting else None,
            title=title,
            link=link,
            scheduled_time=scheduled,
            auto_join=self.auto_join_var.get(),
            mute_mic=self.mic_var.get(),
            mute_camera=self.cam_var.get(),
            recurring=recurring,
            recurring_days=recurring_days,
            join_early_minutes=join_early_minutes,
            notified=self._meeting.notified if self._meeting else False,
            joined=self._meeting.joined if self._meeting else False,
            last_notified_date=self._meeting.last_notified_date if self._meeting else "",
            last_joined_date=self._meeting.last_joined_date if self._meeting else "",
            chrome_connection=chrome_connection,
        )
        self.destroy()


class ConnectionAddEditDialog(tk.Toplevel):
    """Add or edit a single named Chrome connection."""

    def __init__(self, parent, existing: dict | None = None):
        super().__init__(parent)
        self.configure(bg=COLORS["bg"])
        self.title("Edit connection" if existing else "Add connection")
        self.resizable(False, False)
        self.grab_set()
        self.result: dict | None = None
        pad = {"padx": 20, "pady": 7}

        outer = tk.Frame(self, bg=COLORS["bg"])
        outer.pack(fill="both", expand=True)

        heading = "✏️  Edit connection" if existing else "➕  Add a Chrome connection"
        tk.Label(outer, text=heading, bg=COLORS["bg"], fg=COLORS["text"], font=FONTS["heading"]).grid(
            row=0, column=0, columnspan=3, sticky="w", padx=20, pady=(18, 10)
        )

        ttk.Label(outer, text="Name (just a label for you)").grid(row=1, column=0, sticky="w", **pad)
        self.name_var = tk.StringVar(value=existing["name"] if existing else "")
        ttk.Entry(outer, textvariable=self.name_var, width=36).grid(row=1, column=1, columnspan=2, **pad)

        self.backend_var = tk.StringVar(value=existing["backend"] if existing else "uia")
        ttk.Radiobutton(
            outer, text="Launch/attach automatically, no manual setup (recommended, Windows only)",
            variable=self.backend_var, value="uia", command=self._toggle_backend,
        ).grid(row=2, column=0, columnspan=3, sticky="w", **pad)
        ttk.Radiobutton(
            outer, text="Attach via debug port (doesn't work on your real profile since Chrome 136 - see README)",
            variable=self.backend_var, value="cdp", command=self._toggle_backend,
        ).grid(row=3, column=0, columnspan=3, sticky="w", **pad)

        ttk.Separator(outer, orient="horizontal").grid(row=4, column=0, columnspan=3, sticky="ew", padx=20, pady=8)

        # --- UIA fields ---
        self.uia_frame = tk.Frame(outer, bg=COLORS["bg"])
        self.uia_frame.grid(row=5, column=0, columnspan=3, sticky="w")
        ttk.Label(self.uia_frame, text="Chrome profile directory name").grid(row=0, column=0, sticky="w", **pad)
        self.uia_profile_var = tk.StringVar(value=existing.get("profile_directory", "") if existing else "")
        ttk.Entry(self.uia_frame, textvariable=self.uia_profile_var, width=32).grid(row=0, column=1, **pad)
        ttk.Label(
            self.uia_frame,
            text="Find this via chrome://version in that specific profile's Chrome\n"
                 "window - use the last folder from 'Profile Path', not the display\n"
                 "name shown in Chrome's UI. Once set, this works whether Chrome is\n"
                 "already open or closed - a fresh, dedicated window opens either way.",
            justify="left", foreground=COLORS["text_secondary"],
        ).grid(row=1, column=0, columnspan=2, sticky="w", padx=20)

        ttk.Separator(self.uia_frame, orient="horizontal").grid(row=2, column=0, columnspan=2, sticky="ew", padx=20, pady=8)

        ttk.Label(
            self.uia_frame,
            text="Advanced fallback (only used if profile directory above is blank):\n"
                 "attach to an already-open window instead, matched by title.\n"
                 "Requires Chrome to already be running with a matching window.",
            justify="left", foreground=COLORS["text_secondary"],
        ).grid(row=3, column=0, columnspan=2, sticky="w", padx=20)
        ttk.Label(self.uia_frame, text="Window title contains (optional)").grid(row=4, column=0, sticky="w", **pad)
        self.title_hint_var = tk.StringVar(value=existing.get("title_hint", "") if existing else "")
        ttk.Entry(self.uia_frame, textvariable=self.title_hint_var, width=36).grid(row=4, column=1, **pad)
        RoundedButton(
            self.uia_frame, "Detect open Chrome windows", command=self._on_detect, kind="secondary", bg=COLORS["bg"]
        ).grid(row=5, column=0, columnspan=2, sticky="w", padx=20, pady=(2, 6))

        # --- CDP fields ---
        self.cdp_frame = tk.Frame(outer, bg=COLORS["bg"])
        self.cdp_frame.grid(row=5, column=0, columnspan=3, sticky="w")
        ttk.Label(self.cdp_frame, text="Chrome profile directory name").grid(row=0, column=0, sticky="w", **pad)
        self.cdp_profile_var = tk.StringVar(value=existing.get("profile_directory", "") if existing else "")
        ttk.Entry(self.cdp_frame, textvariable=self.cdp_profile_var, width=32).grid(row=0, column=1, **pad)
        ttk.Label(self.cdp_frame, text="Debug port (unique per connection)").grid(row=1, column=0, sticky="w", **pad)
        self.port_var = tk.StringVar(value=str(existing.get("port", 9222)) if existing else "9222")
        ttk.Entry(self.cdp_frame, textvariable=self.port_var, width=10).grid(row=1, column=1, sticky="w", **pad)
        ttk.Label(
            self.cdp_frame,
            text="Find the profile directory name via chrome://version in that\n"
                 "specific profile's Chrome window - use the last folder from\n"
                 "'Profile Path', not the display name shown in Chrome's UI.",
            justify="left", foreground=COLORS["text_secondary"],
        ).grid(row=2, column=0, columnspan=2, sticky="w", padx=20)
        RoundedButton(
            self.cdp_frame, "Test this port", command=self._on_test_port, kind="secondary", bg=COLORS["bg"]
        ).grid(row=3, column=0, columnspan=2, sticky="w", padx=20, pady=(4, 0))

        self.status_var = tk.StringVar(value="")
        ttk.Label(
            outer, textvariable=self.status_var, foreground=COLORS["success"], wraplength=340, justify="left",
        ).grid(row=6, column=0, columnspan=3, sticky="w", **pad)

        btns = tk.Frame(outer, bg=COLORS["bg"])
        btns.grid(row=7, column=0, columnspan=3, pady=(10, 18))
        RoundedButton(btns, "Save", command=self._on_save, kind="primary", bg=COLORS["bg"]).pack(side="left", padx=6)
        RoundedButton(btns, "Cancel", command=self.destroy, kind="secondary", bg=COLORS["bg"]).pack(side="left", padx=6)

        self._toggle_backend()

    def _toggle_backend(self) -> None:
        if self.backend_var.get() == "uia":
            self.cdp_frame.grid_remove()
            self.uia_frame.grid()
        else:
            self.uia_frame.grid_remove()
            self.cdp_frame.grid()

    def _on_detect(self) -> None:
        from src import automation_uia
        titles = automation_uia.list_chrome_windows()
        if not titles:
            messagebox.showinfo(
                "No Chrome windows found",
                "No open Chrome windows were detected. Open Chrome (any profile) "
                "and try again.\n\n(This detection is Windows-only.)",
                parent=self,
            )
            return
        listing = "\n".join(f"• {t}" for t in titles)
        messagebox.showinfo(
            "Open Chrome windows",
            f"Currently open Chrome windows:\n\n{listing}\n\n"
            "Copy a distinctive part of the one you want into 'Window title "
            "contains' above.",
            parent=self,
        )

    def _on_test_port(self) -> None:
        try:
            port = int(self.port_var.get())
        except ValueError:
            messagebox.showerror("Invalid port", "Port must be a number.", parent=self)
            return
        from src import cdp_probe
        info = cdp_probe.probe_port(port, timeout=1.5)
        if info:
            browser = info.get("Browser", "unknown")
            self.status_var.set(f"✓ Found a live Chrome on port {port} ({browser}).")
        else:
            self.status_var.set(
                f"✗ Nothing answering on port {port} yet. Run this connection's "
                "launcher script first, then test again."
            )

    def _on_save(self) -> None:
        from src import automation_uia
        name = self.name_var.get().strip()
        if not name:
            messagebox.showerror("Missing info", "Name is required.", parent=self)
            return
        backend = self.backend_var.get()
        if backend == "uia":
            self.result = {
                "name": name, "backend": "uia",
                "profile_directory": automation_uia._normalize_profile_directory(self.uia_profile_var.get()),
                "title_hint": self.title_hint_var.get().strip(),
            }
        else:
            profile_directory = automation_uia._normalize_profile_directory(self.cdp_profile_var.get())
            if not profile_directory:
                messagebox.showerror("Missing info", "Profile directory name is required.", parent=self)
                return
            try:
                port = int(self.port_var.get())
            except ValueError:
                messagebox.showerror("Invalid port", "Port must be a number.", parent=self)
                return
            self.result = {
                "name": name, "backend": "cdp",
                "profile_directory": profile_directory, "port": port,
            }
        self.destroy()


class ConnectionsManagerDialog(tk.Toplevel):
    """Manage the list of named Chrome connections that classes can be
    assigned to join through."""

    def __init__(self, parent):
        super().__init__(parent)
        self.configure(bg=COLORS["bg"])
        self.title("Chrome connections")
        self.resizable(False, False)
        self.grab_set()

        outer = tk.Frame(self, bg=COLORS["bg"])
        outer.pack(fill="both", expand=True, padx=20, pady=18)

        tk.Label(outer, text="⚙️  Chrome connections", bg=COLORS["bg"], fg=COLORS["text"], font=FONTS["heading"]).pack(
            anchor="w"
        )
        ttk.Label(
            outer,
            text="Each connection is a Chrome window auto-join attaches to - nothing\n"
                 "closes, nothing relaunches. 'No setup' connections use whatever\n"
                 "Chrome window you already have open; 'debug port' connections need\n"
                 "a launcher script but can target one profile precisely among several.",
            justify="left", foreground=COLORS["text_secondary"],
        ).pack(anchor="w", pady=(6, 12))

        table_wrap = tk.Frame(outer, bg=COLORS["border"])
        table_wrap.pack(fill="both", expand=True, pady=(0, 12))
        table_inner = tk.Frame(table_wrap, bg=COLORS["surface"])
        table_inner.pack(fill="both", expand=True, padx=1, pady=1)

        columns = ("name", "backend", "detail", "status")
        self.tree = ttk.Treeview(table_inner, columns=columns, show="headings", height=6, selectmode="browse")
        for col, label, width in [
            ("name", "Name", 150), ("backend", "Type", 100),
            ("detail", "Detail", 150), ("status", "Status", 150),
        ]:
            self.tree.heading(col, text=label)
            self.tree.column(col, width=width, anchor="w")
        self.tree.pack(fill="both", expand=True, padx=1, pady=1)

        btns = tk.Frame(outer, bg=COLORS["bg"])
        btns.pack(fill="x")
        RoundedButton(btns, "＋ Add", command=self._on_add, kind="primary", bg=COLORS["bg"]).pack(side="left", padx=(0, 6))
        RoundedButton(btns, "Edit", command=self._on_edit, kind="secondary", bg=COLORS["bg"]).pack(side="left", padx=6)
        RoundedButton(btns, "Remove", command=self._on_remove, kind="danger", bg=COLORS["bg"]).pack(side="left", padx=6)
        RoundedButton(btns, "Check status", command=self._refresh, kind="secondary", bg=COLORS["bg"]).pack(side="left", padx=6)
        RoundedButton(btns, "Scan for CDP ports", command=self._on_scan, kind="secondary", bg=COLORS["bg"]).pack(side="left", padx=6)
        RoundedButton(btns, "Open launcher folder", command=self._open_launcher_folder, kind="secondary", bg=COLORS["bg"]).pack(side="left", padx=6)
        RoundedButton(btns, "Close", command=self.destroy, kind="secondary", bg=COLORS["bg"]).pack(side="right")

        self._refresh()

    def _refresh(self) -> None:
        from src import cdp_probe
        from src import automation_uia
        self.tree.delete(*self.tree.get_children())
        open_titles = None
        for c in settings.list_connections():
            if c["backend"] == "cdp":
                info = cdp_probe.probe_port(c["port"], timeout=0.5)
                status = "● Running" if info else "○ Not detected"
                detail = f"port {c['port']}"
                backend_label = "Debug port"
            elif c.get("profile_directory"):
                status = "● Ready (launches on demand)"
                detail = f"profile '{c['profile_directory']}'"
                backend_label = "No setup"
            else:
                if open_titles is None:
                    open_titles = automation_uia.list_chrome_windows()
                hint = c.get("title_hint", "")
                if hint:
                    matched = any(hint.lower() in t.lower() for t in open_titles)
                else:
                    matched = bool(open_titles)
                status = "● Chrome open" if matched else "○ Chrome not open"
                detail = f"title has '{hint}'" if hint else "(any open window)"
                backend_label = "No setup (attach)"
            self.tree.insert(
                "", "end", iid=c["name"],
                values=(c["name"], backend_label, detail, status),
            )

    def _on_scan(self) -> None:
        from src import cdp_probe
        found = cdp_probe.scan_for_chrome()
        known_ports = {c["port"] for c in settings.list_connections() if c["backend"] == "cdp"}
        if not found:
            messagebox.showinfo(
                "Scan results",
                "No Chrome instances with a debug port open were found "
                f"on ports {cdp_probe.COMMON_PORT_RANGE.start}-{cdp_probe.COMMON_PORT_RANGE.stop - 1}.\n\n"
                "This only applies to 'debug port' connections. If you're using "
                "'no setup' connections instead, this scan doesn't apply to you.",
                parent=self,
            )
            return
        lines = []
        for f in found:
            tag = " (already configured)" if f["port"] in known_ports else " (not yet configured as a connection)"
            lines.append(f"Port {f['port']}: {f.get('Browser', 'unknown')}{tag}")
        messagebox.showinfo("Scan results", "Found live Chrome debug ports:\n\n" + "\n".join(lines), parent=self)
        self._refresh()

    def _selected_name(self) -> str | None:
        sel = self.tree.selection()
        return sel[0] if sel else None

    def _on_add(self) -> None:
        dlg = ConnectionAddEditDialog(self)
        self.wait_window(dlg)
        if dlg.result:
            self._save_and_generate(dlg.result)

    def _on_edit(self) -> None:
        name = self._selected_name()
        if not name:
            messagebox.showinfo("No selection", "Select a connection to edit first.", parent=self)
            return
        existing = settings.get_connection(name)
        dlg = ConnectionAddEditDialog(self, existing=existing)
        self.wait_window(dlg)
        if dlg.result:
            if dlg.result["name"] != name:
                settings.remove_connection(name)
                from src import launchers
                launchers.remove_launchers(name)
            self._save_and_generate(dlg.result)

    def _save_and_generate(self, result: dict) -> None:
        if result["backend"] == "uia":
            settings.add_or_update_uia_connection(
                result["name"], result.get("title_hint", ""), result.get("profile_directory", "")
            )
            self._refresh()
            if result.get("profile_directory"):
                info_msg = (
                    "No launcher needed - Chrome can be open or closed, this connection "
                    "launches that profile fresh either way. Pick it for any class in "
                    "Add/Edit class."
                )
            else:
                info_msg = (
                    "No profile directory set, so this will only work if Chrome is "
                    "already open with a matching window at class time (see the "
                    "reminder notification). Consider adding a profile directory for "
                    "a more reliable setup."
                )
            messagebox.showinfo("Connection saved", info_msg, parent=self)
        else:
            from src import launchers
            settings.add_or_update_cdp_connection(result["name"], result["profile_directory"], result["port"])
            bat_path, sh_path = launchers.generate_launchers(
                result["name"], result["profile_directory"], result["port"]
            )
            self._refresh()
            messagebox.showinfo(
                "Connection saved",
                f"Launcher scripts generated:\n{bat_path}\n{sh_path}\n\n"
                "Run the one for your OS instead of your normal Chrome icon to start "
                "this profile with its debug port open. Then pick this connection "
                "for any class in Add/Edit class.",
                parent=self,
            )

    def _on_remove(self) -> None:
        name = self._selected_name()
        if not name:
            messagebox.showinfo("No selection", "Select a connection to remove first.", parent=self)
            return
        if messagebox.askyesno("Confirm remove", f"Remove connection '{name}'?", parent=self):
            from src import launchers
            settings.remove_connection(name)
            launchers.remove_launchers(name)
            self._refresh()

    def _open_launcher_folder(self) -> None:
        from src import launchers
        import subprocess
        path = str(launchers.LAUNCHER_DIR)
        try:
            if sys.platform == "win32":
                subprocess.Popen(["explorer", path])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception:
            messagebox.showinfo("Launcher folder", path, parent=self)


# Main application window

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        saved_geometry = settings.get_window_geometry()
        self.geometry(saved_geometry if saved_geometry else "1040x680")
        self.minsize(880, 560)
        self.configure(bg=COLORS["bg"])

        self._setup_style()

        self.store = MeetingStore()
        self.scheduler = SchedulerService(self.store, on_status_change=self._on_scheduler_status)
        self.tray_icon = None  # set up lazily, see tray.py
        self.selected_meeting_id: int | None = None
        self._last_checked_var = tk.StringVar(value="—")
        self._transient_status_var = tk.StringVar(value="Ready")

        self._build_ui()
        self._refresh_all()
        self.scheduler.start()

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(5000, self._periodic_refresh)

    # ---------- styling ----------

    def _setup_style(self) -> None:
        """Configures ttk globally with the modern palette - this cascades
        automatically to every dialog in the app (buttons, labels, entries,
        checkboxes, comboboxes all pick it up for free)."""
        c = COLORS
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure(".", background=c["bg"], foreground=c["text"], font=FONTS["body"])
        style.configure("TFrame", background=c["bg"])
        style.configure("TLabel", background=c["bg"], foreground=c["text"])
        style.configure("TCheckbutton", background=c["bg"], foreground=c["text"])
        style.configure("TRadiobutton", background=c["bg"], foreground=c["text"])

        style.configure(
            "TButton", background=c["surface"], foreground=c["text"],
            padding=(12, 7), borderwidth=1, relief="flat", focusthickness=0,
        )
        style.map(
            "TButton",
            background=[("active", c["primary_soft"]), ("pressed", c["primary_soft"])],
            bordercolor=[("!disabled", c["border"])],
        )

        style.configure(
            "Treeview", background=c["surface"], fieldbackground=c["surface"],
            foreground=c["text"], rowheight=30, borderwidth=0, font=FONTS["body"],
        )
        style.configure(
            "Treeview.Heading", background=c["primary_soft"], foreground=c["text"],
            font=FONTS["small_bold"], relief="flat", padding=(6, 6),
        )
        style.map("Treeview", background=[("selected", c["primary"])], foreground=[("selected", "white")])
        style.layout("Treeview", [("Treeview.treearea", {"sticky": "nswe"})])

        style.configure("Vertical.TScrollbar", background=c["border"], troughcolor=c["bg"], borderwidth=0)

    # ---------- UI construction ----------

    def _build_ui(self) -> None:
        # --- Header ---
        header = tk.Frame(self, bg=COLORS["primary"])
        header.pack(fill="x")
        header_inner = tk.Frame(header, bg=COLORS["primary"])
        header_inner.pack(fill="x", padx=24, pady=(18, 16))
        tk.Label(
            header_inner, text="🎓  EarlyBird 🐦", bg=COLORS["primary"], fg="#FFFFFF", font=FONTS["title"],
        ).pack(anchor="w")
        tk.Label(
            header_inner, text="Automatic join · mic & camera off · runs quietly in the background",
            bg=COLORS["primary"], fg="#E3E5FD", font=FONTS["subtitle"],
        ).pack(anchor="w", pady=(2, 0))

        # --- Dashboard summary cards ---
        self.dashboard_frame = tk.Frame(self, bg=COLORS["bg"])
        self.dashboard_frame.pack(fill="x", padx=24, pady=(18, 6))

        # --- Toolbar ---
        toolbar = tk.Frame(self, bg=COLORS["bg"])
        toolbar.pack(fill="x", padx=24, pady=(10, 14))
        RoundedButton(toolbar, "＋ Add class", command=self._on_add, kind="primary", bg=COLORS["bg"]).pack(
            side="left", padx=(0, 8)
        )
        RoundedButton(toolbar, "✏️ Edit", command=self._on_edit, kind="secondary", bg=COLORS["bg"]).pack(side="left", padx=4)
        RoundedButton(toolbar, "🗑️ Delete", command=self._on_delete, kind="danger", bg=COLORS["bg"]).pack(side="left", padx=4)
        RoundedButton(toolbar, "🔔 Toggle auto-join", command=self._on_toggle_auto_join, kind="secondary", bg=COLORS["bg"]).pack(
            side="left", padx=4
        )
        RoundedButton(toolbar, "⚙️ Chrome connections", command=self._on_settings, kind="secondary", bg=COLORS["bg"]).pack(
            side="left", padx=4
        )
        RoundedButton(toolbar, "Minimize to tray", command=self._minimize_to_tray, kind="secondary", bg=COLORS["bg"]).pack(
            side="right"
        )

        # --- Meeting list area (scrollable card list, or empty state) ---
        self.list_container = tk.Frame(self, bg=COLORS["bg"])
        self.list_container.pack(fill="both", expand=True, padx=24, pady=(0, 12))

        # --- Status bar ---
        status_bar = tk.Frame(self, bg=COLORS["primary_soft"])
        status_bar.pack(fill="x", side="bottom")
        status_inner = tk.Frame(status_bar, bg=COLORS["primary_soft"])
        status_inner.pack(fill="x", padx=18, pady=8)
        tk.Label(
            status_inner, text="🟢 Scheduler running", bg=COLORS["primary_soft"],
            fg=COLORS["text"], font=FONTS["small_bold"],
        ).pack(side="left")
        tk.Label(
            status_inner, textvariable=self._transient_status_var, bg=COLORS["primary_soft"],
            fg=COLORS["text_secondary"], font=FONTS["small"],
        ).pack(side="left", padx=(14, 0))
        self._last_checked_label = tk.Label(
            status_inner, textvariable=self._last_checked_var, bg=COLORS["primary_soft"],
            fg=COLORS["text_secondary"], font=FONTS["small"],
        )
        self._last_checked_label.pack(side="right")

    # ---------- dashboard ----------

    def _compute_stats(self, meetings: list[Meeting]):
        today = datetime.now().date()
        now = datetime.now()
        todays = [m for m in meetings if recurrence.is_active_on_date(m, today)]
        upcoming = [
            m for m in meetings
            if m.auto_join and (
                (recurrence.is_recurring(m) and recurrence.parse_days(m.recurring_days))
                or (not recurrence.is_recurring(m) and m.scheduled_time > now and not m.joined)
            )
        ]
        joined_today = [
            m for m in meetings
            if (
                recurrence.is_recurring(m) and m.last_joined_date == today.isoformat()
            ) or (
                not recurrence.is_recurring(m) and m.joined and m.scheduled_time.date() == today
            )
        ]
        watching = [m for m in meetings if m.auto_join and (
            recurrence.is_recurring(m) or not m.joined
        )]
        return len(todays), len(upcoming), len(joined_today), len(watching)

    def _make_stat_card(self, parent, icon, value, label, accent):
        card = Card(parent, bg=COLORS["surface"])
        inner = tk.Frame(card, bg=COLORS["surface"])
        inner.pack(fill="both", expand=True, padx=18, pady=14)
        tk.Label(inner, text=icon, bg=COLORS["surface"], font=("Segoe UI", 15)).pack(anchor="w")
        tk.Label(inner, text=str(value), bg=COLORS["surface"], fg=accent, font=FONTS["stat_number"]).pack(
            anchor="w", pady=(4, 0)
        )
        tk.Label(inner, text=label, bg=COLORS["surface"], fg=COLORS["text_secondary"], font=FONTS["small"]).pack(anchor="w")
        return card

    def _rebuild_dashboard(self, meetings: list[Meeting]) -> None:
        for child in self.dashboard_frame.winfo_children():
            child.destroy()
        today_n, upcoming_n, joined_n, watching_n = self._compute_stats(meetings)
        cards = [
            ("📅", today_n, "Today's Classes", COLORS["primary"]),
            ("🕒", upcoming_n, "Upcoming Classes", COLORS["warning"]),
            ("✅", joined_n, "Joined Today", COLORS["success"]),
        ]
        for icon, value, label, accent in cards:
            c = self._make_stat_card(self.dashboard_frame, icon, value, label, accent)
            c.pack(side="left", fill="both", expand=True, padx=(0, 12))
        self._watching_count = watching_n

    # ---------- meeting list ----------

    def _status_badge_spec(self, m: Meeting):
        label = m.status_label()
        if label == "Recurring":
            return "🔁 Recurring", COLORS["primary"], COLORS["primary_soft"]
        if label == "Joined":
            return "🔵 Joined", COLORS["primary"], COLORS["primary_soft"]
        if label == "Manual":
            return "⚪ Manual", COLORS["text_secondary"], COLORS["bg"]
        return "🟢 Scheduled", COLORS["success"], COLORS["success_bg"]

    def _build_meeting_row(self, parent, m: Meeting) -> None:
        is_selected = self.selected_meeting_id == m.id
        row = Card(parent, bg=COLORS["surface"])
        if is_selected:
            row.configure(highlightbackground=COLORS["primary"], highlightthickness=2)
        row.pack(fill="x", pady=(0, 10))

        def select(_e=None, mid=m.id):
            self.selected_meeting_id = mid
            self._refresh_all()

        content = tk.Frame(row, bg=COLORS["surface"], cursor="hand2")
        content.pack(fill="x", padx=16, pady=13)
        content.bind("<Button-1>", select)

        left = tk.Frame(content, bg=COLORS["surface"], cursor="hand2")
        left.pack(side="left", fill="x", expand=True)
        left.bind("<Button-1>", select)

        title_row = tk.Frame(left, bg=COLORS["surface"], cursor="hand2")
        title_row.pack(fill="x", anchor="w")
        title_row.bind("<Button-1>", select)
        title_lbl = tk.Label(title_row, text=m.title, bg=COLORS["surface"], fg=COLORS["text"], font=FONTS["body_bold"])
        title_lbl.pack(side="left")
        title_lbl.bind("<Button-1>", select)

        badge_text, badge_fg, badge_bg = self._status_badge_spec(m)
        badge = make_badge(title_row, badge_text, badge_fg, badge_bg, bg_behind=COLORS["surface"])
        badge.pack(side="left", padx=(10, 0))
        badge.bind("<Button-1>", select)

        conn_label = m.chrome_connection or "Isolated profile"
        auto_label = "Auto-join on" if m.auto_join else "Manual only"
        meta = f"🕒 {m.schedule_summary()}    🔌 {conn_label}    {auto_label}"
        meta_lbl = tk.Label(left, text=meta, bg=COLORS["surface"], fg=COLORS["text_secondary"], font=FONTS["small"])
        meta_lbl.pack(anchor="w", pady=(5, 0))
        meta_lbl.bind("<Button-1>", select)

        link_lbl = tk.Label(left, text=m.link, bg=COLORS["surface"], fg=COLORS["text_secondary"], font=FONTS["small"])
        link_lbl.pack(anchor="w", pady=(2, 0))
        link_lbl.bind("<Button-1>", select)

        right = tk.Frame(content, bg=COLORS["surface"])
        right.pack(side="right")

        def edit_this(mid=m.id):
            self.selected_meeting_id = mid
            self._on_edit()

        def delete_this(mid=m.id):
            self.selected_meeting_id = mid
            self._on_delete()

        def toggle_this(mid=m.id):
            self.selected_meeting_id = mid
            self._on_toggle_auto_join()

        RoundedButton(right, "✏️", command=edit_this, kind="ghost", width=36, height=32, bg=COLORS["surface"]).pack(
            side="left", padx=2
        )
        RoundedButton(right, "🔔", command=toggle_this, kind="ghost", width=36, height=32, bg=COLORS["surface"]).pack(
            side="left", padx=2
        )
        RoundedButton(right, "🗑️", command=delete_this, kind="ghost", width=36, height=32, bg=COLORS["surface"]).pack(
            side="left", padx=2
        )

    def _build_empty_state(self, parent) -> None:
        wrap = tk.Frame(parent, bg=COLORS["bg"])
        wrap.pack(fill="both", expand=True)
        center = tk.Frame(wrap, bg=COLORS["bg"])
        center.place(relx=0.5, rely=0.42, anchor="center")
        tk.Label(center, text="🎓", bg=COLORS["bg"], font=FONTS["empty_icon"]).pack()
        tk.Label(
            center, text="No scheduled classes yet.", bg=COLORS["bg"], fg=COLORS["text"], font=FONTS["heading"],
        ).pack(pady=(10, 2))
        tk.Label(
            center, text='Press "＋ Add class" above to create your first schedule.',
            bg=COLORS["bg"], fg=COLORS["text_secondary"], font=FONTS["body"],
        ).pack()

    def _rebuild_meeting_list(self, meetings: list[Meeting]) -> None:
        for child in self.list_container.winfo_children():
            child.destroy()
        if not meetings:
            self._build_empty_state(self.list_container)
            return
        scroller = ScrollableFrame(self.list_container, bg=COLORS["bg"])
        scroller.pack(fill="both", expand=True)
        for m in meetings:
            self._build_meeting_row(scroller.body, m)

    # ---------- data refresh ----------

    def _refresh_all(self) -> None:
        meetings = sorted(self.store.all(), key=lambda m: m.scheduled_time)
        self._rebuild_dashboard(meetings)
        self._rebuild_meeting_list(meetings)

    def _periodic_refresh(self) -> None:
        self._refresh_all()
        watching = getattr(self, "_watching_count", 0)
        stamp = datetime.now().strftime("%I:%M:%S %p").lstrip("0")
        self._last_checked_var.set(f"Watching {watching} meetings  ·  Last checked {stamp}")
        self.after(5000, self._periodic_refresh)

    def _selected_meeting(self) -> Meeting | None:
        if self.selected_meeting_id is None:
            return None
        return self.store.get(self.selected_meeting_id)

    # ---------- button handlers ----------

    def _on_add(self) -> None:
        dlg = MeetingDialog(self)
        self.wait_window(dlg)
        if dlg.result:
            new_id = self.store.add(dlg.result)
            self.selected_meeting_id = new_id
            self._refresh_all()

    def _on_edit(self) -> None:
        m = self._selected_meeting()
        if not m:
            messagebox.showinfo("No selection", "Select a class to edit first.")
            return
        dlg = MeetingDialog(self, meeting=m)
        self.wait_window(dlg)
        if dlg.result:
            self.store.update(dlg.result)
            self._refresh_all()

    def _on_delete(self) -> None:
        m = self._selected_meeting()
        if not m:
            messagebox.showinfo("No selection", "Select a class to delete first.")
            return
        if messagebox.askyesno("Confirm delete", f"Delete '{m.title}'?"):
            self.store.delete(m.id)
            self.selected_meeting_id = None
            self._refresh_all()

    def _on_toggle_auto_join(self) -> None:
        m = self._selected_meeting()
        if not m:
            messagebox.showinfo("No selection", "Select a class first.")
            return
        m.auto_join = not m.auto_join
        self.store.update(m)
        self._refresh_all()

    def _on_settings(self) -> None:
        dlg = ConnectionsManagerDialog(self)
        self.wait_window(dlg)

    def _on_scheduler_status(self, message: str) -> None:
        self.after(0, lambda: self._transient_status_var.set(message))

    # ---------- tray / lifecycle ----------

    def _minimize_to_tray(self) -> None:
        from src import tray
        self.withdraw()
        if not self.tray_icon:
            self.tray_icon = tray.build_tray_icon(restore_callback=self._restore_from_tray, quit_callback=self._quit)
            threading.Thread(target=self.tray_icon.run, daemon=True).start()

    def _restore_from_tray(self) -> None:
        self.after(0, self.deiconify)

    def _on_close(self) -> None:
        if messagebox.askyesno(
            "Close or minimize?",
            "Minimize to tray and keep auto-joining in the background? "
            "(Choose 'No' to quit the app entirely.)",
        ):
            self._minimize_to_tray()
        else:
            self._quit()

    def _quit(self) -> None:
        try:
            settings.save_window_geometry(self.geometry())
        except Exception:
            pass
        self.scheduler.stop()
        if self.tray_icon:
            self.tray_icon.stop()
        self.destroy()


if __name__ == "__main__":
    app = App()
    app.mainloop()
