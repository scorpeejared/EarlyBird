"""
Generates a small launcher script for each configured Chrome connection.

Chrome only exposes its remote-debugging port when started with the flag
at launch time - there's no supported way to turn it on for an already-
running process. So each connection gets its own tiny script that starts
Chrome, for that one profile, on that one port. Run it once (pin it to
your taskbar/dock for convenience) instead of your normal Chrome icon;
after that, use Chrome completely normally until you reboot.
"""
import stat
from pathlib import Path

LAUNCHER_DIR = Path(__file__).parent / "launchers"
LAUNCHER_DIR.mkdir(exist_ok=True)

CHROME_EXE_WINDOWS = r"C:\Program Files\Google\Chrome\Application\chrome.exe"


def _safe_filename(name: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in name.strip()) or "connection"


def generate_launchers(name: str, profile_directory: str, port: int) -> tuple[Path, Path]:
    """Writes both a .bat (Windows) and .sh (Mac/Linux) launcher for this
    connection and returns their paths. Harmless to generate both regardless
    of your OS - you'll just use whichever one applies to you."""
    safe = _safe_filename(name)

    bat_path = LAUNCHER_DIR / f"launch_{safe}.bat"
    bat_path.write_text(
        "@echo off\n"
        f"REM Chrome connection '{name}': profile '{profile_directory}', "
        f"debug port {port}.\n"
        "REM Run this instead of your normal Chrome icon. Once open, use\n"
        "REM Chrome completely normally - auto-join just attaches to it.\n"
        "\n"
        "REM Chrome only turns on the debug port for a genuinely NEW process.\n"
        "REM If any Chrome window is already open anywhere, this silently\n"
        "REM does nothing useful - it just opens a window in that existing\n"
        "REM process and the debug port never activates. So check first.\n"
        'tasklist /FI "IMAGENAME eq chrome.exe" 2^>NUL | find /I "chrome.exe" >NUL\n'
        "if %ERRORLEVEL%==0 (\n"
        "  echo.\n"
        "  echo WARNING: Chrome is already running on this PC.\n"
        "  echo This launcher will NOT enable the debug port while any Chrome\n"
        "  echo process is open - not even a different profile's window.\n"
        "  echo.\n"
        "  echo Close ALL Chrome windows, then check Task Manager's Details tab\n"
        "  echo for any lingering chrome.exe processes and End Task on them too.\n"
        "  echo Then run this script again.\n"
        "  echo.\n"
        "  pause\n"
        "  exit /b 1\n"
        ")\n"
        "\n"
        f'start "" "{CHROME_EXE_WINDOWS}" ^\n'
        f"  --remote-debugging-port={port} ^\n"
        f'  --profile-directory="{profile_directory}"\n'
    )

    sh_path = LAUNCHER_DIR / f"launch_{safe}.sh"
    sh_path.write_text(
        "#!/bin/bash\n"
        f"# Chrome connection '{name}': profile '{profile_directory}', "
        f"debug port {port}.\n"
        "# Run this instead of your normal Chrome icon. Once open, use\n"
        "# Chrome completely normally - auto-join just attaches to it.\n"
        "\n"
        "# Chrome only turns on the debug port for a genuinely NEW process.\n"
        "# If any Chrome window is already open, this silently does nothing\n"
        "# useful - it just opens a window in that existing process instead.\n"
        "if pgrep -f -i \"google-chrome|Google Chrome\" > /dev/null 2>&1; then\n"
        "    echo\n"
        "    echo \"WARNING: Chrome is already running.\"\n"
        "    echo \"This launcher will NOT enable the debug port while any\"\n"
        "    echo \"Chrome process is open - not even a different profile.\"\n"
        "    echo \"Quit Chrome completely first, then run this again.\"\n"
        "    echo\n"
        "    exit 1\n"
        "fi\n"
        "\n"
        'if [[ "$OSTYPE" == "darwin"* ]]; then\n'
        '    CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"\n'
        "else\n"
        '    CHROME="google-chrome"\n'
        "fi\n"
        f'"$CHROME" --remote-debugging-port={port} --profile-directory="{profile_directory}" &\n'
    )
    try:
        sh_path.chmod(sh_path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    except OSError:
        pass

    return bat_path, sh_path


def remove_launchers(name: str) -> None:
    safe = _safe_filename(name)
    for ext in ("bat", "sh"):
        p = LAUNCHER_DIR / f"launch_{safe}.{ext}"
        if p.exists():
            p.unlink()
