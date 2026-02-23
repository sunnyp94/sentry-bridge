"""
Shared logging: stderr + optional log file. LOG_LEVEL from env (default INFO). LOG_FILE for path (default data/app.log).
Call init() at startup from consumer.main or redis_consumer.main so brain/strategy/executor loggers use it.
"""
import logging
import os
import sys
from pathlib import Path


def init() -> None:
    """Configure root logger: LOG_LEVEL, format to stderr and to LOG_FILE (default data/app.log)."""
    level_name = (os.environ.get("LOG_LEVEL") or "INFO").strip().upper()
    level = getattr(logging, level_name, logging.INFO)
    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"
    formatter = logging.Formatter(fmt, datefmt=datefmt)

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(formatter)
    root.addHandler(handler)

    log_path = (os.environ.get("LOG_FILE") or "data/app.log").strip()
    if log_path:
        try:
            p = Path(log_path).resolve()
            p.parent.mkdir(parents=True, exist_ok=True)
            file_handler = logging.FileHandler(p, encoding="utf-8", mode="a")
            file_handler.setFormatter(formatter)
            root.addHandler(file_handler)
        except Exception as e:
            root.warning("log file %s not used: %s", log_path, e)
