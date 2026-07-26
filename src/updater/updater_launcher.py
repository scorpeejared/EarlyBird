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
$logPath = "{log_path}"
function Log($msg) {{
    $line = "$(Get-Date -Format 'HH:mm:ss') $msg"
    Add-Content -Path $logPath -Value $line
}}

Log "=== EarlyBird updater started ==="

try {{
    # 1. Wait for EarlyBird to fully exit (no-op if it already has).
    Log "Waiting for pid {pid} to exit..."
    Wait-Process -Id {pid} -Timeout 30 -ErrorAction SilentlyContinue
    Log "Wait-Process returned (process exited or wasn't running)."

    # Give the OS a moment to release file handles even after the
    # process object reports exited - a onedir build keeps DLLs
    # loaded directly from disk the whole time it runs, so locks can
    # briefly outlive the process itself.
    Start-Sleep -Milliseconds 1000

    # 2. Swap the app's top-level items (the exe, and for a onedir
    # build its _internal/ folder) as whole units - rename the old one
    # aside, move the new one in. This is deliberately NOT a recursive
    # per-file copy: a onedir build's _internal folder can contain
    # hundreds of DLLs, and copying them one at a time means any single
    # still-locked file leaves a broken mix of old and new files behind.
    # A folder rename/move is a single filesystem operation per item,
    # so there's nothing to partially fail *within* an item.
    $stageDir = "{stage_dir}"
    $installDir = "{install_dir}"
    $preserve = @({preserve_list})
    $suffix = Get-Date -Format "yyyyMMdd_HHmmss"

    $topItems = Get-ChildItem -Path $stageDir | Where-Object {{ $preserve -notcontains $_.Name }}
    Log "Items to install: $($topItems.Name -join ', ')"

    $backups = @()   # items successfully renamed aside, for rollback
    $installed = @()  # new items successfully moved in, for rollback
    $aborted = $false

    foreach ($item in $topItems) {{
        $destPath = Join-Path $installDir $item.Name

        if (Test-Path $destPath) {{
            $backupName = "$($item.Name).bak_$suffix"
            $backupPath = Join-Path $installDir $backupName
            try {{
                Rename-Item -Path $destPath -NewName $backupName -Force -ErrorAction Stop
                $backups += @{{ Orig = $destPath; Backup = $backupPath }}
                Log "Backed up existing '$($item.Name)' -> '$backupName'"
            }} catch {{
                Log "ABORT: failed to back up '$($item.Name)': $($_.Exception.Message)"
                $aborted = $true
                break
            }}
        }}

        try {{
            Move-Item -Path $item.FullName -Destination $destPath -Force -ErrorAction Stop
            $installed += $destPath
            Log "Installed new '$($item.Name)'"
        }} catch {{
            Log "ABORT: failed to move in new '$($item.Name)': $($_.Exception.Message)"
            $aborted = $true
            break
        }}
    }}

    if ($aborted) {{
        Log "Update failed partway - rolling back to the previous version..."
        foreach ($p in $installed) {{
            Remove-Item -Path $p -Recurse -Force -ErrorAction SilentlyContinue
        }}
        foreach ($b in $backups) {{
            Rename-Item -Path $b.Backup -NewName (Split-Path $b.Orig -Leaf) -Force -ErrorAction SilentlyContinue
        }}
        Log "Rollback complete - the previous version should still be intact."
    }} else {{
        Log "All items installed successfully."
    }}

    # 3. Relaunch EarlyBird - same install path either way: on
    # success it's the new version, on rollback it's the restored
    # previous version, so the app comes back either way rather than
    # leaving the user with nothing running.
    Log "Relaunching: {relaunch_exe}"
    try {{
        Start-Process -FilePath "{relaunch_exe}" -ErrorAction Stop
        Log "Start-Process succeeded."
    }} catch {{
        Log "Start-Process FAILED: $($_.Exception.Message)"
    }}

    # 4. Clean up: remove backups only after a successful install
    # (best-effort - a leftover .bak folder doesn't break anything,
    # it just wastes a little disk space until the next update).
    if (-not $aborted) {{
        foreach ($b in $backups) {{
            try {{
                Remove-Item -Path $b.Backup -Recurse -Force -ErrorAction Stop
                Log "Removed backup '$(Split-Path $b.Backup -Leaf)'"
            }} catch {{
                Log "Could not remove backup '$(Split-Path $b.Backup -Leaf)': $($_.Exception.Message)"
            }}
        }}
    }}
    try {{
        Remove-Item -Path $stageDir -Recurse -Force -ErrorAction Stop
        Log "Removed staged download folder."
    }} catch {{
        Log "Could not remove staged download folder: $($_.Exception.Message)"
    }}

    Log "=== Done ==="
}} catch {{
    Log "UNEXPECTED ERROR: $($_.Exception.Message)"
}}
"""


def launch(
    stage_dir: Path,
    install_dir: Path,
    relaunch_exe: Path,
    updates_root: Path,
    current_pid: int | None = None,
) -> Path:
    """Write and launch the detached updater script.

    Call this *before* the app exits - it waits for `current_pid`
    (defaulting to this process's own PID) to disappear, so it's safe
    to launch first and then close the app normally afterward.

    Returns the path to the log file the script writes to as it runs
    (wait/copy/relaunch/cleanup, one line per step) - if an update
    silently doesn't seem to have happened, that log is the first
    place to look, since PowerShell errors have nowhere else to go
    once this runs detached with no console window.
    """
    pid = current_pid if current_pid is not None else __import__("os").getpid()

    log_path = updates_root / "apply_update.log"
    preserve_list = ", ".join(f'"{name}"' for name in _PRESERVE_NAMES)
    script = _SCRIPT_TEMPLATE.format(
        pid=pid,
        stage_dir=str(stage_dir),
        install_dir=str(install_dir),
        preserve_list=preserve_list,
        relaunch_exe=str(relaunch_exe),
        log_path=str(log_path),
    )

    script_path = updates_root / "apply_update.ps1"
    script_path.write_text(script, encoding="utf-8")

    creationflags = 0
    if sys.platform == "win32":
        # Deliberately NOT combining DETACHED_PROCESS with
        # CREATE_NO_WINDOW - Windows documents these as mutually
        # exclusive for CreateProcess, and combining them can make the
        # call fail outright. CREATE_NO_WINDOW alone already hides the
        # console for a console-subsystem app like powershell.exe;
        # CREATE_NEW_PROCESS_GROUP keeps it from being tied to this
        # process's lifetime/signals.
        CREATE_NEW_PROCESS_GROUP = 0x00000200
        CREATE_NO_WINDOW = 0x08000000
        creationflags = CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW

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
    logger.info(
        "Launched detached updater process (script: %s, log: %s, waiting on pid %d)",
        script_path, log_path, pid,
    )
    return log_path
