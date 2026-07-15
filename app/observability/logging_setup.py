"""Structured JSON logging (Loki-friendly)."""

from __future__ import annotations

import logging
import sys

from pythonjsonlogger.json import JsonFormatter


def setup_logging(level: str = "INFO", service: str = "llmops-chat") -> None:
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level.upper())

    handler = logging.StreamHandler(sys.stdout)
    formatter = JsonFormatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s %(service)s",
        rename_fields={"asctime": "timestamp", "levelname": "level", "name": "logger"},
    )
    # Attach service field via LoggerAdapter-friendly filter
    old_factory = logging.getLogRecordFactory()

    def record_factory(*args, **kwargs):  # type: ignore[no-untyped-def]
        record = old_factory(*args, **kwargs)
        if not hasattr(record, "service"):
            record.service = service  # type: ignore[attr-defined]
        return record

    logging.setLogRecordFactory(record_factory)
    handler.setFormatter(formatter)
    root.addHandler(handler)

    # Quiet noisy libs
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
