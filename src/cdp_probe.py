"""
Detects Chrome instances that actually have a remote-debugging port open.

Chrome serves a read-only /json/version endpoint on whatever port it was
started with --remote-debugging-port=<port>; this queries that and nothing
else. A Chrome opened normally has no debug port, so it will not show up
here - that is a Chrome limitation, not a gap in the scan.
"""
from __future__ import annotations

import json
import urllib.request
import urllib.error

COMMON_PORT_RANGE = range(9222, 9232)  # covers the defaults this app suggests


def probe_port(port: int, timeout: float = 0.5) -> dict | None:
    """Chrome's /json/version info if a live DevTools endpoint is
    answering on this port, else None."""
    try:
        with urllib.request.urlopen(f"http://localhost:{port}/json/version", timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except (urllib.error.URLError, TimeoutError, ConnectionError, ValueError, OSError):
        return None


def scan_for_chrome(ports=COMMON_PORT_RANGE) -> list[dict]:
    """Every port in the range running a debuggable Chrome, each entry
    carrying the port plus what Chrome reports about itself."""
    found = []
    for port in ports:
        info = probe_port(port)
        if info:
            found.append({"port": port, **info})
    return found
