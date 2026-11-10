"""
Structured logging configuration.

Call ``setup_logging()`` once at application startup to configure the
root logger with both a console handler and an optional file handler.
"""

from __future__ import annotations

import logging
import sys


def setup_logging(level: int = logging.INFO) -> None:
    """
    Configure the root logger with a consistent format.

    * **Console** – coloured, human-readable output to ``stderr``.
    * Library loggers (``httpx``, ``openai``, ``httpcore``) are quietened
      to WARNING to avoid noisy request-level chatter.
    """
    fmt = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"

    logging.basicConfig(
        level=level,
        format=fmt,
        datefmt=datefmt,
        handlers=[logging.StreamHandler(sys.stderr)],
    )

    # Quieten noisy third-party loggers
    for name in ("httpx", "openai", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)
