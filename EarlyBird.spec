# -*- mode: python ; coding: utf-8 -*-
# Build with:  pyinstaller EarlyBird.spec
# Produces:    dist/EarlyBird/EarlyBird.exe  (onedir build, recommended)

block_cipher = None

hidden_imports = [
    "pystray._win32",
    "PIL._tkinter_finder",
    "win32timezone",
    "win32com",
    "win32com.client",
    "pywinauto.application",
    "pywinauto.findwindows",
    "comtypes",
    "comtypes.stream",
    "playwright.sync_api",
    # src/*.py files import each other using bare names (e.g. "import automation",
    # "from storage import MeetingStore") rather than "from src import automation".
    # That only works at runtime because main.py inserts the src/ folder into
    # sys.path. PyInstaller's static analysis doesn't know to look there unless
    # we tell it, so list every src module explicitly here as a safety net.
    "automation",
    "automation_uia",
    "cdp_probe",
    "launchers",
    "models",
    "notifier",
    "recurrence",
    "scheduler",
    "settings",
    "storage",
    "tray",
]

a = Analysis(
    ["main.py"],
    # Also add src/ to the search path so PyInstaller can actually resolve
    # those bare-name imports above to real files, not just guess at them.
    pathex=["src"],
    binaries=[],
    datas=[],
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="EarlyBird",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,   # no terminal window (this is a GUI + tray app)
    icon=None,       # put a .ico path here if you add an icon later
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="EarlyBird",
)
