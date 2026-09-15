"""Structured application logging configuration."""

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any
from app.core.config import get_settings


class JSONFormatter(logging.Formatter):
    """Formats log records as single-line JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        log_payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Include exception info if present
        if record.exc_info:
            log_payload["exception"] = self.formatException(record.exc_info)

        # Include extra context attributes passed to logger calls
        extra_fields = {
            k: v
            for k, v in record.__dict__.items()
            if k not in {
                "args", "asctime", "created", "exc_info", "exc_text", "filename",
                "funcName", "levelname", "levelno", "lineno", "module", "msecs",
                "message", "msg", "name", "pathname", "process", "processName",
                "relativeCreated", "stack_info", "thread", "threadName",
            }
        }
        if extra_fields:
            log_payload["extra"] = extra_fields

        return json.dumps(log_payload, default=str)


class TextFormatter(logging.Formatter):
    """Clean readable log formatter for local development."""

    def __init__(self) -> None:
        super().__init__(
            fmt="%(asctime)s | %(levelname)-8s | %(name)s:%(lineno)d - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )


def setup_logging() -> logging.Logger:
    """Configure root logger with structured formatting based on settings."""
    settings = get_settings()
    log_level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # Clear existing handlers
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)

    if settings.LOG_FORMAT == "json":
        console_handler.setFormatter(JSONFormatter())
    else:
        console_handler.setFormatter(TextFormatter())

    root_logger.addHandler(console_handler)

    # Adjust external noisy loggers
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(
        logging.INFO if settings.DB_ECHO else logging.WARNING
    )

    app_logger = logging.getLogger("nexus")
    app_logger.info(
        "Structured logging initialized",
        extra={"environment": settings.APP_ENV, "format": settings.LOG_FORMAT},
    )
    return app_logger


def get_logger(name: str = "nexus") -> logging.Logger:
    """Get a logger instance with the given name."""
    return logging.getLogger(name)
