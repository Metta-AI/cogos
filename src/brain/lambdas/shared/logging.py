"""Structured JSON logging for CloudWatch."""

from __future__ import annotations

import json
import logging
import sys


class JsonFormatter(logging.Formatter):
    """Format log records as single-line JSON for CloudWatch."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry: dict = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
        }
        if hasattr(record, "run_id"):
            log_entry["run_id"] = record.run_id
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_entry)


def setup_logging(level: str = "INFO") -> logging.Logger:
    """Configure root logger with JSON formatter for CloudWatch."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(getattr(logging, level))
    return root
