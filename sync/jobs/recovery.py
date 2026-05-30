from __future__ import annotations

import logging

from hub.client import HubClient
from sync.jobs.files import cleanup_orphan_files, delete_job_file
from sync.jobs.store import list_active_jobs, load_job, save_job

logger = logging.getLogger("multishop.sync_jobs")

_TERMINAL_HUB_STATUSES = frozenset(
    {"completed", "failed", "cancelled", "interrupted"}
)


def _push_delegated_to_hub(remote: dict) -> bool:
    """Archivo ya en el hub y process en curso: el nodo no debe cortar el job."""
    if str(remote.get("direction") or "").strip().lower() != "push":
        return False
    status = str(remote.get("status") or "").strip().lower()
    if status not in {"pending", "running"}:
        return False
    phase = str(remote.get("phase") or "").strip().lower()
    if phase in {"upload", "process"}:
        return True
    return bool(remote.get("fileSizeBytes") or remote.get("fileSha256"))


def _finalize_local_push_delegated(
    job_id: str, data: dict, remote_status: str
) -> None:
    save_job(
        job_id,
        {
            **data,
            "status": "uploaded",
            "direction": data.get("direction") or "push",
            "phase": data.get("phase") or "process",
            "hub_status": remote_status,
        },
    )
    delete_job_file(job_id)


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
            remote = await hub.get_sync_job(job_id)
            remote_status = str(remote.get("status") or "").strip().lower()
            if remote_status in _TERMINAL_HUB_STATUSES:
                logger.info(
                    "Skip interrupt job_id=%s hub already %s",
                    job_id,
                    remote_status,
                )
                save_job(
                    job_id,
                    {
                        **data,
                        "status": remote_status,
                    },
                )
                delete_job_file(job_id)
                continue
            if remote_status not in {"pending", "running"}:
                delete_job_file(job_id)
                continue
            if _push_delegated_to_hub(remote):
                logger.info(
                    "Push job_id=%s delegado al hub (hub=%s); no marcar interrupted",
                    job_id,
                    remote_status,
                )
                _finalize_local_push_delegated(job_id, data, remote_status)
                continue
            await hub.patch_sync_job_progress(
                job_id,
                {
                    "status": "interrupted",
                    "error_message": (
                        "Job interrupted on node. Retry catalog push/pull inventory."
                    ),
                },
            )
        except Exception as exc:
            logger.warning("Could not report interrupted job %s: %s", job_id, exc)
        save_job(job_id, {**data, "status": "interrupted"})
        delete_job_file(job_id)
