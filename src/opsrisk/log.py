"""Logging setup: readable text locally, one JSON object per line in CI."""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone

# Attributes every LogRecord has; anything else was passed through ``extra``.
_STANDARD = set(vars(logging.makeLogRecord({}))) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(
                timespec="seconds"
            ),
            "level": record.levelname.lower(),
            "logger": record.name,
            "msg": record.getMessage(),
        }
        payload.update({k: v for k, v in vars(record).items() if k not in _STANDARD})
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


class TextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        extras = " ".join(
            f"{k}={v}" for k, v in vars(record).items()
            if k not in _STANDARD and v not in (None, "")
        )
        line = f"[{record.levelname}] {record.getMessage()}"
        return f"{line} {extras}" if extras else line


def setup_logging(fmt: str = "text", level: str = "WARNING") -> None:
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter() if fmt == "json" else TextFormatter())
    root = logging.getLogger("opsrisk")
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    root.propagate = False
