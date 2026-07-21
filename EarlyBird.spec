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
]

a = Analysis(
    ["main.py"],
    pathex=[],
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
