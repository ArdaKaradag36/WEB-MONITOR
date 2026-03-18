from __future__ import annotations

import logging
from typing import Optional

from rich.console import Console
from rich.logging import RichHandler

_LOGGER_NAME = "watchdog"
_console = Console()


def configure_logging(level: int = logging.INFO) -> logging.Logger:
    """
    Configure and return the root logger for WatchDog.

    The logger uses Rich's RichHandler for structured, colorful console output.
    Subsequent calls are idempotent and will reuse existing handlers.

    :param level: Logging level, defaults to logging.INFO.
    :return: Configured logger instance.
    """
    logger = logging.getLogger(_LOGGER_NAME)

    if not logger.handlers:
        handler = RichHandler(console=_console, rich_tracebacks=True, show_time=True)
        formatter = logging.Formatter(
            "%(message)s",
            datefmt="[%X]",
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    logger.setLevel(level)
    logger.propagate = False
    return logger


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """
    Get a child logger for a specific module or component.

    :param name: Optional child logger name suffix.
    :return: Logger instance.
    """
    if name:
        return logging.getLogger(f"{_LOGGER_NAME}.{name}")
    return logging.getLogger(_LOGGER_NAME)


__all__ = ["configure_logging", "get_logger"]
