"""ASCII-safe logging for Windows consoles (cp1252) and generic terminals."""

from __future__ import annotations

import logging
import os
import sys
from typing import Any

# Shared runtime error strings (English, ASCII only).
MYSQL_NOT_CONFIGURED = "Node MySQL not configured (set MYSQL_* in .env)"
SYNC_STORE_NOT_INIT = "sync_store not initialized"
OUTBOX_REPO_NOT_INIT = "outbox_repo not initialized"
HUB_BASE_URL_NOT_SET = "HUB_BASE_URL not set"
HUB_PUSH_REQUIRES_MYSQL = "HUB_PUSH_ENABLED requires MYSQL_* configured"
HUEY_REQUIRES_MYSQL = "HUEY_ENABLED requires MYSQL_* configured"


def ascii_safe(value: Any) -> str:
    """Coerce any value to an ASCII log string (non-ASCII escaped or dropped)."""
    text = str(value)
    return text.encode("ascii", errors="backslashreplace").decode("ascii")


class AsciiSafeLogFilter(logging.Filter):
    """Ensure log records never crash handlers on non-ASCII text."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = ascii_safe(record.msg)
        if record.args:
            record.args = tuple(
                ascii_safe(arg) if isinstance(arg, str) else arg for arg in record.args
            )
        return True


def configure_stdio_utf8() -> None:
    if sys.platform != "win32":
        return
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except OSError:
                pass


def configure_node_logging(*, logger_names: tuple[str, ...] = ()) -> None:
    configure_stdio_utf8()

    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    root = logging.getLogger()
    if not root.handlers:
        logging.basicConfig(
            level=level,
            format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        )
    else:
        root.setLevel(level)

    ascii_filter = AsciiSafeLogFilter()
    root.addFilter(ascii_filter)
    for name in logger_names:
        logging.getLogger(name).setLevel(level)
