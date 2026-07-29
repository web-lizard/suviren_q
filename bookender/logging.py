"""Structured local logging without book text or secrets."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .paths import LOGS_DIR, ensure_user_directories


LOGGER_NAME = "bookender"


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "event": getattr(record, "event", record.getMessage()),
        }
        context = getattr(record, "context", None)
        if isinstance(context, dict):
            payload["context"] = context
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def get_logger() -> logging.Logger:
    ensure_user_directories()
    logger = logging.getLogger(LOGGER_NAME)
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    handler = logging.FileHandler(
        LOGS_DIR / "bookender.log", encoding="utf-8", delay=True
    )
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    logger.propagate = False
    return logger


def log_event(event: str, **context: Any) -> None:
    get_logger().info(event, extra={"event": event, "context": context})
