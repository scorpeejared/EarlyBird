"""
Spawns a standalone updater process that outlives EarlyBird itself.

Why a separate process at all: the running .exe can't overwrite or
delete its own file on Windows, so *something* has to do the file swap
after EarlyBird has fully exited. That something is a small,
self-deleting PowerShell script, launched detached from this process
right before EarlyBird closes.

A generated script (rather than a second compiled .exe shipped
alongside the app) is the pragmatic choice today: it needs no separate
PyInstaller build/signing pipeline to maintain, and PowerShell is
present on every supported Windows version. If that ever becomes
limiting (e.g. wanting a signed updater binary for stricter AV/SmartScreen
behavior), swap the implementation inside `launch()` for one that writes
the staged files' paths to a small companion exe instead - nothing
outside this module needs to change, since update_manager only calls
`launch()`.

Safety note: the swap step explicitly skips `data/`, `logs/`, and any
`*.db`/`settings.json` files by name, so a user's meetings and settings
are never touched by an update, whether today's onefile layout or a
future onedir layout is in play.
"""
from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger("meet_automation")

_PRESERVE_NAMES = {"data", "logs", "settings.json"}

_SCRIPT_TEMPLATE = r"""
$ErrorActionPreference = "SilentlyContinue"

# 1. Wait for EarlyBird to fully exit (no-op if it already has).
Wait-Process -Id {pid} -Timeout 30

# Give the OS a moment to release file handles even after the process
# object reports exited - immediate copies right after Wait-Process can
# still hit a "file in use" error on some systems.
Start-Sleep -Milliseconds 750

# 2. Copy staged files over the install directory, preserving user data.
$stageDir = "{stage_dir}"
$installDir = "{install_dir}"
$preserve = @({preserve_list})

Get-ChildItem -Path $stageDir -Recurse -File | ForEach-Object {{
    $relative = $_.FullName.Substring($stageDir.Length).TrimStart('\')
    $topLevel = ($relative -split '\\')[0]
    if ($preserve -contains $topLevel) {{ return }}

    $target = Join-Path $installDir $relative
    $targetDir = Split-Path $target -Parent
    if (-not (Test-Path $targetDir)) {{
        New-Item -ItemType Directory -Path $targetDir -Force | Out-Null
    }}

    $copied = $false
    for ($i = 0; $i -lt 5 -and -not $copied; $i++) {{
        try {{
            Copy-Item -Path $_.FullName -Destination $target -Force -ErrorAction Stop
            $copied = $true
        }} catch {{
            Start-Sleep -Milliseconds 500
        }}
    }}
}}

# 3. Relaunch EarlyBird.
Start-Process -FilePath "{relaunch_exe}"

# 4. Clean up the staged download.
Remove-Item -Path "{updates_root}" -Recurse -Force

# 5. Self-delete this script.
Remove-Item -Path "$PSCommandPath" -Force
"""


def launch(
    stage_dir: Path,
    install_dir: Path,
    relaunch_exe: Path,
    updates_root: Path,
    current_pid: int | None = None,
) -> None:
    """Write and launch the detached updater script.

    Call this *before* the app exits - it waits for `current_pid`
    (defaulting to this process's own PID) to disappear, so it's safe
    to launch first and then close the app normally afterward.
    """
    pid = current_pid if current_pid is not None else __import__("os").getpid()

    preserve_list = ", ".join(f'"{name}"' for name in _PRESERVE_NAMES)
    script = _SCRIPT_TEMPLATE.format(
        pid=pid,
        stage_dir=str(stage_dir),
        install_dir=str(install_dir),
        preserve_list=preserve_list,
        relaunch_exe=str(relaunch_exe),
        updates_root=str(updates_root),
    )

    script_path = updates_root / "apply_update.ps1"
    script_path.write_text(script, encoding="utf-8")

    creationflags = 0
    if sys.platform == "win32":
        DETACHED_PROCESS = 0x00000008
        CREATE_NEW_PROCESS_GROUP = 0x00000200
        CREATE_NO_WINDOW = 0x08000000
        creationflags = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW

    subprocess.Popen(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy", "Bypass",
            "-WindowStyle", "Hidden",
            "-File", str(script_path),
        ],
        creationflags=creationflags,
        close_fds=True,
    )
    logger.info("Launched detached updater process (script: %s, waiting on pid %d)", script_path, pid)
