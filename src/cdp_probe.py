"""
Detects Chrome instances that actually have a remote-debugging port open.

Chrome exposes a small read-only HTTP endpoint (/json/version) on whatever
port it was started with --remote-debugging-port=<port>. We just query
that - no process injection, no reaching into Chrome's internals, just the
same status page Chrome itself serves for DevTools to use.

If a Chrome window was opened normally (double-click icon, no launcher),
it has no debug port at all, so there's nothing to find - that's a Chrome
limitation (see automation.py's docstring), not a bug in this scan.
"""
from __future__ import annotations

import json
import urllib.request
import urllib.error

COMMON_PORT_RANGE = range(9222, 9232)  # covers the defaults this app suggests


def probe_port(port: int, timeout: float = 0.5) -> dict | None:
    """Returns Chrome's /json/version info if something is listening and
    answering as a real Chrome DevTools endpoint on this port, else None."""
    try:
        with urllib.request.urlopen(f"http://localhost:{port}/json/version", timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except (urllib.error.URLError, TimeoutError, ConnectionError, ValueError, OSError):
        return None


def scan_for_chrome(ports=COMMON_PORT_RANGE) -> list[dict]:
    """Scans a range of ports and returns info for every one that's a live,
    debuggable Chrome instance. Each result includes the port and whatever
    Chrome reports about itself (browser version, user agent)."""
    found = []
    for port in ports:
        info = probe_port(port)
        if info:
            found.append({"port": port, **info})
    return found
