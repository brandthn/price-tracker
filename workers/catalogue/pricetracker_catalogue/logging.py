from __future__ import annotations

import logging
import sys


"""class StructuredLogger(logging.Logger):
    def info(self, msg, *args, **kwargs):
        if kwargs:
            msg = f"{msg} | " + " ".join(f"{k}={v}" for k, v in kwargs.items())
        super().info(msg, *args)"""

class StructuredLogger(logging.Logger):
    def _fmt(self, msg, kwargs):
        if kwargs:
            return f"{msg} | " + " ".join(f"{k}={v}" for k, v in kwargs.items())
        return msg

    def info(self, msg, *args, **kwargs):
        super().info(self._fmt(msg, kwargs), *args)

    def warning(self, msg, *args, **kwargs):
        super().warning(self._fmt(msg, kwargs), *args)

    def error(self, msg, *args, **kwargs):
        super().error(self._fmt(msg, kwargs), *args)

    def debug(self, msg, *args, **kwargs):
        super().debug(self._fmt(msg, kwargs), *args)


def get_logger(name: str) -> logging.Logger:
    logging.setLoggerClass(StructuredLogger)

    logger = logging.getLogger(name)

    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(
            logging.Formatter(
                fmt="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)

    return logger




"""Logging structuré — même pattern que les autres workers du projet."""
"""from __future__ import annotations

import logging
import sys


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(
            logging.Formatter(
                fmt="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger
"""