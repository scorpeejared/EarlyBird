"""
Spawns a standalone updater process that outlives EarlyBird itself.

The running .exe can't overwrite its own file on Windows, so the swap is
done by a detached PowerShell script, launched just before EarlyBird
closes and waiting on its PID. A generated script rather than a second
compiled binary keeps it out of the PyInstaller build and signing setup;
`launch()` is the only entry point, so that choice is swappable.

The swap skips the names in _PRESERVE_NAMES, so an update never touches
a user's meetings or settings.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from ..logging_setup import get_logger

logger = get_logger()

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

    # File locks can briefly outlive the process itself, so give the
    # OS a moment to release the handles.
    Start-Sleep -Milliseconds 1000

    # 2. Swap each top-level item (the exe, plus _internal/ on a onedir
    # build) as a whole unit: rename the old aside, move the new in.
    # Not a per-file copy - one still-locked DLL out of hundreds would
    # leave a broken mix of old and new behind. A rename/move is a
    # single filesystem operation, so it can't half-fail within an item.
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

    # 3. Relaunch from the same install path either way - the new
    # version on success, the restored one after a rollback - so the
    # user is never left with nothing running.
    Log "Relaunching: {relaunch_exe}"
    try {{
        Start-Process -FilePath "{relaunch_exe}" -ErrorAction Stop
        Log "Start-Process succeeded."
    }} catch {{
        Log "Start-Process FAILED: $($_.Exception.Message)"
    }}

    # 4. Remove backups only after a successful install. Best-effort: a
    # leftover .bak folder just wastes disk until the next update.
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

    Call this *before* the app exits: it waits for `current_pid`
    (this process by default) to disappear, so launching first and
    closing afterwards is the intended order.

    Returns the path of the log the script writes as it runs - the only
    place its errors can surface, since it runs with no console window.
    """
    pid = current_pid if current_pid is not None else os.getpid()

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
        # Not DETACHED_PROCESS: Windows documents it as mutually
        # exclusive with CREATE_NO_WINDOW, which alone already hides
        # powershell.exe's console. CREATE_NEW_PROCESS_GROUP is what
        # unties the script from this process's lifetime and signals.
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
