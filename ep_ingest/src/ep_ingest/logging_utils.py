from __future__ import annotations

import logging
import uuid


class _CorrelationFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "correlation_id"):
            record.correlation_id = "-"
        return True


def configure_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    if root.handlers:
        return
    handler = logging.StreamHandler()
    handler.addFilter(_CorrelationFilter())
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s [corr=%(correlation_id)s] %(name)s - %(message)s"
    )
    handler.setFormatter(formatter)
    root.addHandler(handler)
    root.setLevel(level.upper())


def new_correlation_id() -> str:
    return uuid.uuid4().hex


def get_logger(name: str, correlation_id: str) -> logging.LoggerAdapter:
    base = logging.getLogger(name)
    return logging.LoggerAdapter(base, extra={"correlation_id": correlation_id})
