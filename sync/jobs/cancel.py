from __future__ import annotations

from sync.jobs.store import load_job, save_job


class JobCancelledError(Exception):
    """El job fue cancelado desde admin (hub) o localmente en la tienda."""


def request_local_cancel(job_id: str) -> None:
    data = load_job(job_id) or {"job_id": job_id}
    data["cancel_requested"] = True
    data["status"] = "cancelled"
    save_job(job_id, data)


def is_job_cancelled(job_id: str) -> bool:
    data = load_job(job_id)
    if not data:
        return False
    if data.get("cancel_requested"):
        return True
    return str(data.get("status") or "").strip().lower() == "cancelled"


def ensure_not_cancelled_sync(job_id: str) -> None:
    if is_job_cancelled(job_id):
        raise JobCancelledError(f"Job {job_id} cancelado")


async def ensure_hub_job_active(hub, job_id: str) -> None:
    """Comprueba estado en hub antes de subir/completar (p. ej. cancel offline)."""
    remote = await hub.get_sync_job(job_id)
    status = str(remote.get("status") or "").strip().lower()
    if status == "cancelled":
        request_local_cancel(job_id)
        raise JobCancelledError(f"Job {job_id} cancelado en hub")


async def ensure_job_active(hub, job_id: str) -> None:
    ensure_not_cancelled_sync(job_id)
    await ensure_hub_job_active(hub, job_id)
