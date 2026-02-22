"""
Shared logging: one handler to stderr with timestamp, level, logger name. LOG_LEVEL from env (default INFO).
Call init() at startup from consumer.main or redis_consumer.main so brain/strategy/executor loggers use it.
"""
import logging
import os
import sys


def init() -> None:
    """Configure root logger: LOG_LEVEL (DEBUG/INFO/WARN/ERROR), format to stderr."""
    level_name = (os.environ.get("LOG_LEVEL") or "INFO").strip().upper()
    level = getattr(logging, level_name, logging.INFO)
    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter(fmt, datefmt=datefmt))
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()
    root.addHandler(handler)
