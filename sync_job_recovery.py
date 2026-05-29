from __future__ import annotations

import logging

from hub_client import HubClient
from sync_job_files import cleanup_orphan_files, delete_job_file
from sync_job_store import list_active_jobs, load_job, save_job

logger = logging.getLogger("multishop.sync_jobs")


async def recover_stale_local_jobs() -> None:
    active = set(list_active_jobs())
    removed = cleanup_orphan_files(active)
    if removed:
        logger.info("Removed %s orphan sync job files", removed)

    hub = None
    for job_id in active:
        data = load_job(job_id) or {}
        if data.get("status") not in {"pending", "running"}:
            delete_job_file(job_id)
            continue
        try:
            if hub is None:
                hub = HubClient()
            await hub.patch_sync_job_progress(
                job_id,
                {
                    "status": "interrupted",
                    "error_message": (
                        "El job quedó a mitad en el nodo. Relance push/pull inventario."
                    ),
                },
            )
        except Exception as exc:
            logger.warning("Could not report interrupted job %s: %s", job_id, exc)
        save_job(job_id, {**data, "status": "interrupted"})
        delete_job_file(job_id)
