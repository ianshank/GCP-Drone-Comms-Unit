"""structlog configuration (mirrors ``meshsa.cli.configure_logging``).

Lives in one place so every entry point wires structlog identically: JSON output
for production, coloured console output for development, with a filtering level.
"""

from __future__ import annotations

import logging

import structlog


def log_level_num(name: str) -> int:
    """Map a level name (case-insensitive) to its numeric value; unknown -> INFO."""
    value = logging.getLevelName(name.upper())
    return value if isinstance(value, int) else logging.INFO


def configure_logging(level: str = "INFO", *, json_logs: bool = False) -> None:
    """Configure structlog's processors and filtering level.

    ``json_logs=True`` emits machine-readable JSON (production); otherwise a
    human-friendly coloured console renderer is used (development).
    """
    shared: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
    ]
    renderer: structlog.types.Processor = (
        structlog.processors.JSONRenderer() if json_logs else structlog.dev.ConsoleRenderer()
    )
    structlog.configure(
        processors=[*shared, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(log_level_num(level)),
        cache_logger_on_first_use=True,
    )
