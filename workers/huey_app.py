from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from huey import SqliteHuey

from core.config import settings


def _ensure_parent_dir(path: str) -> None:
    p = Path(path)
    parent = p.parent
    if str(parent) and not parent.exists():
        parent.mkdir(parents=True, exist_ok=True)


_ensure_parent_dir(settings.huey_db_path)

huey = SqliteHuey(
    name="multishop-nodo",
    filename=settings.huey_db_path,
    immediate=False,
)

logger = logging.getLogger("multishop.outbox")
