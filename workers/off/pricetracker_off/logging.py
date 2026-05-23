"""structlog → stdout JSON. Cf. worker-ingestion pour la justification."""

from __future__ import annotations

import logging
import sys

import structlog


def _add_severity(_logger: object, method_name: str, event_dict: dict) -> dict:
    event_dict["severity"] = method_name.upper()
    return event_dict


def configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=level,
        format="%(message)s",
        stream=sys.stdout,
        force=True,
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            _add_severity,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.EventRenamer("message"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str = "pricetracker_off") -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
