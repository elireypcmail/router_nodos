from __future__ import annotations

import time
from typing import Any

from hub.client import HubClient

_last_report: dict[str, tuple[float, int]] = {}


async def report_progress(
    hub: HubClient,
    job_id: str,
    *,
    phase: str,
    progress_nodo: int,
    total_rows: int | None = None,
    processed_rows: int | None = None,
    force: bool = False,
) -> None:
    from core.config import settings as app_settings

    throttle_ms = int(app_settings.catalog_sync_progress_throttle_ms)
    now = time.time()
    last = _last_report.get(job_id)
    if (
        not force
        and last is not None
        and (now - last[0]) * 1000 < throttle_ms
        and abs(progress_nodo - last[1]) < 1
    ):
        return
    _last_report[job_id] = (now, progress_nodo)
    body: dict[str, Any] = {
        "phase": phase,
        "progress_nodo": min(100, max(0, progress_nodo)),
    }
    if total_rows is not None:
        body["total_rows"] = total_rows
    if processed_rows is not None:
        body["processed_rows"] = processed_rows
    await hub.patch_sync_job_progress(job_id, body)
