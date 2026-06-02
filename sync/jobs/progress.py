from __future__ import annotations

import logging
import time
from typing import Any

from hub.client import HubClient
from sync.jobs.export_progress import should_tick_export_loop

logger = logging.getLogger("multishop.sync.progress")

_last_report: dict[str, tuple[float, int]] = {}


async def report_progress(
    hub: HubClient,
    job_id: str,
    *,
    phase: str,
    progress_nodo: int,
    progress_hub: int | None = None,
    total_rows: int | None = None,
    processed_rows: int | None = None,
    force: bool = False,
    raise_on_error: bool = False,
) -> bool:
    """
    Reporta progreso al hub. Por defecto no aborta el export si el hub responde 503.
    """
    from core.config import settings as app_settings

    throttle_ms = int(app_settings.catalog_sync_progress_throttle_ms)
    now = time.time()
    last = _last_report.get(job_id)

    row_tick = False
    if processed_rows is not None and total_rows is not None and total_rows > 0:
        row_tick = should_tick_export_loop(
            written=int(processed_rows),
            total=int(total_rows),
        )

    if (
        not force
        and not row_tick
        and last is not None
        and (now - last[0]) * 1000 < throttle_ms
        and abs(progress_nodo - last[1]) < 1
    ):
        return True
    _last_report[job_id] = (now, progress_nodo)
    body: dict[str, Any] = {
        "phase": phase,
        "progress_nodo": min(100, max(0, progress_nodo)),
    }
    if progress_hub is not None:
        body["progress_hub"] = min(100, max(0, progress_hub))
    if total_rows is not None:
        body["total_rows"] = total_rows
    if processed_rows is not None:
        body["processed_rows"] = processed_rows
    try:
        await hub.patch_sync_job_progress(job_id, body)
        return True
    except Exception as exc:
        logger.warning(
            "patch progress job=%s phase=%s pct=%s failed: %s",
            job_id,
            phase,
            progress_nodo,
            exc,
        )
        if raise_on_error:
            raise
        return False
