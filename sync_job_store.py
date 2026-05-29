from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from config import settings


def _store_dir() -> Path:
    p = Path(settings.nodo_sync_jobs_dir) / "state"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _path(job_id: str) -> Path:
    return _store_dir() / f"{job_id}.json"


def load_job(job_id: str) -> dict[str, Any] | None:
    path = _path(job_id)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def save_job(job_id: str, data: dict[str, Any]) -> None:
    path = _path(job_id)
    path.write_text(json.dumps(data, ensure_ascii=True), encoding="utf-8")


def list_active_jobs() -> list[str]:
    active: list[str] = []
    for path in _store_dir().glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("status") in {"pending", "running"}:
                active.append(path.stem)
        except (OSError, json.JSONDecodeError):
            continue
    return active
