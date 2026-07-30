"""
Shared logging setup: one logger name and one log file for the whole app.

``configure()`` is called once from main(); every other module just calls
``get_logger()``.
"""
from __future__ import annotations

import logging

from . import paths

LOGGER_NAME = "earlybird"
LOG_FILENAME = "automation.log"


def configure() -> None:
    """Point the root logger at logs/automation.log. Safe to call twice."""
    paths.LOG_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=paths.LOG_DIR / LOG_FILENAME,
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )


def get_logger() -> logging.Logger:
    return logging.getLogger(LOGGER_NAME)
