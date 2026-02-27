"""
Shared logging: stderr + optional log file. LOG_LEVEL from env (default INFO). LOG_FILE for path (default data/app.log).
Uses RotatingFileHandler so only recent logs are kept; very old data is overwritten (10 MB per file, 5 backups = ~60 MB max).
Call init() at startup from consumer.main so brain/strategy/executor loggers use it.
"""
import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

# Keep last ~60 MB of logs: 10 MB per file, 5 backups; older data is overwritten
LOG_ROTATE_MAX_BYTES = 10 * 1024 * 1024  # 10 MB
LOG_ROTATE_BACKUP_COUNT = 5


def init() -> None:
    """Configure root logger: LOG_LEVEL, format to stderr and to LOG_FILE (default data/app.log) with rotation."""
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
            file_handler = RotatingFileHandler(
                p,
                encoding="utf-8",
                maxBytes=LOG_ROTATE_MAX_BYTES,
                backupCount=LOG_ROTATE_BACKUP_COUNT,
            )
            file_handler.setFormatter(formatter)
            root.addHandler(file_handler)
        except Exception as e:
            root.warning("log file %s not used: %s", log_path, e)
