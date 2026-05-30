from __future__ import annotations

import os
from pathlib import Path

from core.config import settings


def jobs_dir() -> Path:
    p = Path(settings.nodo_sync_jobs_dir)
    p.mkdir(parents=True, exist_ok=True)
    return p


def job_file_path(job_id: str) -> Path:
    return jobs_dir() / f"{job_id}.ndjson.gz"


def delete_job_file(job_id: str) -> None:
    path = job_file_path(job_id)
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass
    tmp = Path(f"{path}.uploading")
    try:
        tmp.unlink(missing_ok=True)
    except OSError:
        pass


def cleanup_orphan_files(active_job_ids: set[str] | None = None) -> int:
    removed = 0
    active = active_job_ids or set()
    for entry in jobs_dir().glob("*.ndjson.gz"):
        job_id = entry.name.replace(".ndjson.gz", "")
        if job_id not in active:
            try:
                entry.unlink()
                removed += 1
            except OSError:
                pass
    return removed
