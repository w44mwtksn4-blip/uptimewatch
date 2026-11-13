"""Console plus rotating-file logging."""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"


def setup_logging(log_file: Path, level: str = "INFO") -> None:
    """Log to stderr and to ``log_file`` (1 MB per file, 3 backups)."""
    root = logging.getLogger()
    root.setLevel(level.upper())
    root.handlers.clear()  # safe to call twice

    formatter = logging.Formatter(FORMAT)
    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(formatter)
    root.addHandler(console)

    try:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            log_file, maxBytes=1_000_000, backupCount=3, encoding="utf-8"
        )
    except OSError as exc:
        logging.getLogger(__name__).warning(
            "File logging disabled, cannot open %s (%s)", log_file, exc.strerror or exc
        )
        return
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    # urllib3 debug lines can contain request URLs; keep them out of the logs.
    logging.getLogger("urllib3").setLevel(logging.WARNING)
