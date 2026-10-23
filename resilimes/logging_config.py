"""JSON logs with secret redaction. Stdlib only, so the demo image stays small."""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime
from typing import Any

_SECRET = re.compile(r"(?i)(authorization|api[_-]?key|token|secret|password|bearer)\s*[:=]\s*\S+")


def redact(text: str) -> str:
    return _SECRET.sub(r"\1=[redacted]", text)


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": redact(record.getMessage()),
        }
        extra = getattr(record, "fields", None)
        if isinstance(extra, dict):
            payload["fields"] = {str(key): redact(str(value)) for key, value in extra.items()}
        if record.exc_info:
            payload["exc"] = redact(self.formatException(record.exc_info))
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    root.handlers.clear()
    handler = logging.StreamHandler()
    handler.setFormatter(_JsonFormatter())
    root.addHandler(handler)
    root.setLevel(level.upper())
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
