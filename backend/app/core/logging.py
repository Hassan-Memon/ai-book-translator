"""Logging setup. Uses rich when a TTY is present, plain formatting otherwise."""

from __future__ import annotations

import logging
import sys

from app.core.config import settings

_CONFIGURED = False


def setup_logging() -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return

    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    handler: logging.Handler

    if sys.stderr.isatty():
        from rich.logging import RichHandler

        handler = RichHandler(rich_tracebacks=True, show_path=False)
        fmt = "%(message)s"
    else:
        handler = logging.StreamHandler(sys.stderr)
        fmt = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"

    handler.setFormatter(logging.Formatter(fmt, datefmt="%H:%M:%S"))
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)

    # These are chatty at DEBUG and drown out pipeline progress.
    for noisy in ("httpx", "httpcore", "openai", "urllib3", "asyncio"):
        logging.getLogger(noisy).setLevel(max(level, logging.WARNING))

    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    setup_logging()
    return logging.getLogger(name)
