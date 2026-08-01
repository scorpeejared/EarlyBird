"""
Generates a small launcher script for each configured browser connection.

Chromium browsers only expose the remote-debugging port when started with
the flag at launch time - there's no supported way to turn it on for an
already-running process. So each connection gets its own tiny script that
starts that browser, for that one profile, on that one port. Run it once
(pin it to your taskbar/dock for convenience) instead of your normal
browser icon; after that, use the browser completely normally until you
reboot.

Everything browser-specific (exe path, process image name, the macOS app
bundle) is looked up per browser; the script body itself is the same shape
for all of them, so the Chrome scripts are byte-for-byte what they were.
"""
import stat
from pathlib import Path

from . import browsers, paths

LAUNCHER_DIR = paths.LAUNCHER_DIR
LAUNCHER_DIR.mkdir(parents=True, exist_ok=True)

CHROME_EXE_WINDOWS = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

# Per-browser values the launcher scripts need. The Windows exe is the
# first candidate path from browsers.py (what a default install uses);
# the rest are the shapes the shell script needs on macOS/Linux.
_LAUNCHER_SPECS = {
    browsers.CHROME: {
        "exe_windows": CHROME_EXE_WINDOWS,
        "image": "chrome.exe",
        "macos": "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "linux": "google-chrome",
        "pgrep": "google-chrome|Google Chrome",
    },
    browsers.EDGE: {
        "exe_windows": r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        "image": "msedge.exe",
        "macos": "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        "linux": "microsoft-edge",
        "pgrep": "microsoft-edge|Microsoft Edge",
    },
    browsers.BRAVE: {
        "exe_windows": r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
        "image": "brave.exe",
        "macos": "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
        "linux": "brave-browser",
        "pgrep": "brave-browser|Brave Browser",
    },
    # %LOCALAPPDATA% is left unexpanded on purpose - cmd.exe expands it at run
    # time, so one generated script works for whoever runs it.
    browsers.OPERA: {
        "exe_windows": r"%LOCALAPPDATA%\Programs\Opera\opera.exe",
        "image": "opera.exe",
        "macos": "/Applications/Opera.app/Contents/MacOS/Opera",
        "linux": "opera",
        "pgrep": "opera",
    },
    browsers.OPERA_GX: {
        "exe_windows": r"%LOCALAPPDATA%\Programs\Opera GX\opera.exe",
        "image": "opera.exe",
        "macos": "/Applications/Opera GX.app/Contents/MacOS/Opera",
        "linux": "opera",
        "pgrep": "opera",
    },
}


def _spec(browser: str) -> dict:
    return _LAUNCHER_SPECS.get(browsers.normalize(browser), _LAUNCHER_SPECS[browsers.CHROME])


def _safe_filename(name: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in name.strip()) or "connection"


def generate_launchers(
    name: str,
    profile_directory: str,
    port: int,
    browser: str = browsers.DEFAULT,
) -> tuple[Path, Path]:
    """Write a .bat (Windows) and .sh (Mac/Linux) launcher for this
    connection and return both paths; you use whichever fits your OS."""
    safe = _safe_filename(name)
    spec = _spec(browser)
    label = browsers.short_name(browser)
    exe = spec["exe_windows"]
    image = spec["image"]
    # Shell variable named after the browser, so Chrome's script stays exactly
    # the text it has always been.
    var = label.upper().replace(" ", "_")
    # --profile-directory="X" for Chromium; Opera also needs the --user-data-dir
    # its profile lives in, so this can be more than one flag.
    profile_args = browsers.profile_launch_args(browser, profile_directory)
    if not profile_args:
        profile_args = [f"--profile-directory={profile_directory}"]
    quoted = [f'{flag}="{val}"' for flag, val in (a.split("=", 1) for a in profile_args)]
    bat_profile_args = " ^\n  ".join(quoted)
    sh_profile_args = " ".join(quoted)

    bat_path = LAUNCHER_DIR / f"launch_{safe}.bat"
    bat_path.write_text(
        "@echo off\n"
        f"REM {label} connection '{name}': profile '{profile_directory}', "
        f"debug port {port}.\n"
        f"REM Run this instead of your normal {label} icon. Once open, use\n"
        f"REM {label} completely normally - auto-join just attaches to it.\n"
        "\n"
        f"REM {label} only turns on the debug port for a genuinely NEW process.\n"
        f"REM If any {label} window is already open anywhere, this silently\n"
        "REM does nothing useful - it just opens a window in that existing\n"
        "REM process and the debug port never activates. So check first.\n"
        f'tasklist /FI "IMAGENAME eq {image}" 2^>NUL | find /I "{image}" >NUL\n'
        "if %ERRORLEVEL%==0 (\n"
        "  echo.\n"
        f"  echo WARNING: {label} is already running on this PC.\n"
        f"  echo This launcher will NOT enable the debug port while any {label}\n"
        "  echo process is open - not even a different profile's window.\n"
        "  echo.\n"
        f"  echo Close ALL {label} windows, then check Task Manager's Details tab\n"
        f"  echo for any lingering {image} processes and End Task on them too.\n"
        "  echo Then run this script again.\n"
        "  echo.\n"
        "  pause\n"
        "  exit /b 1\n"
        ")\n"
        "\n"
        f'start "" "{exe}" ^\n'
        f"  --remote-debugging-port={port} ^\n"
        f"  {bat_profile_args}\n"
    )

    sh_path = LAUNCHER_DIR / f"launch_{safe}.sh"
    sh_path.write_text(
        "#!/bin/bash\n"
        f"# {label} connection '{name}': profile '{profile_directory}', "
        f"debug port {port}.\n"
        f"# Run this instead of your normal {label} icon. Once open, use\n"
        f"# {label} completely normally - auto-join just attaches to it.\n"
        "\n"
        f"# {label} only turns on the debug port for a genuinely NEW process.\n"
        f"# If any {label} window is already open, this silently does nothing\n"
        "# useful - it just opens a window in that existing process instead.\n"
        f"if pgrep -f -i \"{spec['pgrep']}\" > /dev/null 2>&1; then\n"
        "    echo\n"
        f'    echo "WARNING: {label} is already running."\n'
        '    echo "This launcher will NOT enable the debug port while any"\n'
        f'    echo "{label} process is open - not even a different profile."\n'
        f'    echo "Quit {label} completely first, then run this again."\n'
        "    echo\n"
        "    exit 1\n"
        "fi\n"
        "\n"
        'if [[ "$OSTYPE" == "darwin"* ]]; then\n'
        f'    {var}="{spec["macos"]}"\n'
        "else\n"
        f'    {var}="{spec["linux"]}"\n'
        "fi\n"
        f'"${var}" --remote-debugging-port={port} {sh_profile_args} &\n'
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
