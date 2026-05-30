from __future__ import annotations

import logging
from typing import Any

import anyio

from core.config import settings
from core.log_compat import configure_node_logging, ascii_safe
from db.mysql import MySqlClient
from hub.client import HubClient
from workers.huey_app import huey
from outbox.mysql import OutboxRepository
from sync.jobs.export import export_inventory_push_file
from sync.jobs.files import delete_job_file, job_file_path
from sync.jobs.progress import report_progress
from sync.jobs.pull_file import run_inventory_pull_from_file
from sync.jobs.store import save_job

logger = logging.getLogger("multishop.outbox")

configure_node_logging()

def run_outbox_flush_once() -> dict[str, Any]:
    """Reserve pending rows and send one batch to the hub."""
    mysql = MySqlClient()
    if not mysql.is_configured():
        raise RuntimeError("Huey outbox requires MYSQL_* configured")

    repo = OutboxRepository(mysql)
    recovered = repo.recover_processing()
    if recovered:
        logger.warning("Outbox: recovered %s row(s) from processing", recovered)
    hub = HubClient()

    events = repo.reserve_pending(limit=int(settings.huey_outbox_batch_size))
    if not events:
        return {"sent": 0, "ignored": 0, "failed": 0, "message": "no_pending"}

    payload: list[dict[str, Any]] = []
    ids: list[int] = []
    for e in events:
        payload.append(
            {
                "outbox_id": e.id,
                "table": e.table_name,
                "op": e.op,
                "pk": e.pk,
                "row": e.row,
                "created_at": e.created_at,
            }
        )
        ids.append(e.id)

    try:
        result = anyio.run(hub.send_outbox_batch, payload)
        repo.apply_send_result(result)
        return {
            "sent": len(result.sent_ids),
            "ignored": len(result.ignored_ids),
            "failed": len(result.failed_ids),
            "message": "ok" if not result.has_failures else "partial_failure",
        }
    except Exception as ex:
        repo.release_to_pending(ids, ascii_safe(ex))
        raise


@huey.task(retries=settings.huey_outbox_task_retries, retry_delay=settings.huey_outbox_retry_delay_seconds)
def send_outbox_batch() -> dict[str, Any]:
    """Huey task: reserve a pending outbox batch and send it to the hub."""
    return run_outbox_flush_once()


# Prioridad baja: jobs de catálogo (pull/push) deben adelantarse en la cola.
_OUTBOX_PRIORITY = 0
_CATALOG_JOB_PRIORITY = 10


@huey.task()
def enqueue_outbox() -> dict[str, Any]:
    """Compat con tareas viejas en huey.sqlite; ya no reprograma (usar outbox_tick)."""
    return run_outbox_flush_once()


@huey.task()
def outbox_tick() -> dict[str, Any]:
    """Un solo latido de outbox; reprograma solo outbox_tick (no duplicar cadenas)."""
    try:
        return run_outbox_flush_once()
    finally:
        delay_sec = max(
            1, int(float(settings.huey_outbox_enqueue_interval_seconds))
        )
        outbox_tick.schedule(delay=delay_sec, priority=_OUTBOX_PRIORITY)


def bootstrap_outbox_scheduler() -> None:
    """Tras arranque API: limpia schedules duplicados y arma una sola cadena outbox_tick."""
    huey.storage.flush_schedule()
    outbox_tick.schedule(delay=0, priority=_OUTBOX_PRIORITY)
    logger.info("Outbox Huey: schedule limpiado, outbox_tick armado")


def schedule_catalog_pull_job(job_id: str) -> None:
    """Encola ejecución inmediata (huey.enqueue), no schedule() que exige delay/eta."""
    logger.info("Encolando catalog pull job_id=%s (priority=%s)", job_id, _CATALOG_JOB_PRIORITY)
    catalog_pull_job(job_id, priority=_CATALOG_JOB_PRIORITY)


def schedule_catalog_push_job(job_id: str) -> None:
    logger.info("Encolando catalog push job_id=%s (priority=%s)", job_id, _CATALOG_JOB_PRIORITY)
    catalog_push_job(job_id, priority=_CATALOG_JOB_PRIORITY)


@huey.task(retries=3, retry_delay=30)
def catalog_push_job(job_id: str) -> dict:
    return anyio.run(_catalog_push_job_async, job_id)


@huey.task(retries=3, retry_delay=30)
def catalog_pull_job(job_id: str) -> dict:
    return anyio.run(_catalog_pull_job_async, job_id)


async def _catalog_push_job_async(job_id: str) -> dict:
    mysql = MySqlClient()
    if not mysql.is_configured():
        raise RuntimeError("MYSQL_* required for catalog push job")
    hub = HubClient()
    save_job(
        job_id,
        {"job_id": job_id, "direction": "push", "status": "running", "phase": "export"},
    )

    def on_export(done: int, total: int, pct: int) -> None:
        async def _report() -> None:
            await report_progress(
                hub,
                job_id,
                phase="export",
                progress_nodo=pct,
                total_rows=total,
                processed_rows=done,
            )

        anyio.from_thread.run(_report)

    try:
        path, total = await anyio.to_thread.run_sync(
            lambda: export_inventory_push_file(
                job_id,
                mysql,
                settings.nodo_id,
                on_progress=on_export,
            )
        )
        await report_progress(
            hub,
            job_id,
            phase="upload",
            progress_nodo=55,
            total_rows=total,
            force=True,
        )
        await hub.upload_sync_job_file(job_id, path)
        delete_job_file(job_id)
        await report_progress(
            hub,
            job_id,
            phase="process",
            progress_nodo=100,
            total_rows=total,
            force=True,
        )
        # uploaded = trabajo del nodo terminado; el hub sigue en phase process (no listar como activo local).
        save_job(
            job_id,
            {
                "job_id": job_id,
                "direction": "push",
                "status": "uploaded",
                "phase": "process",
            },
        )
        return {"job_id": job_id, "status": "uploaded", "total_rows": total}
    except Exception as ex:
        save_job(job_id, {"job_id": job_id, "status": "failed", "error": str(ex)})
        delete_job_file(job_id)
        try:
            await hub.patch_sync_job_progress(
                job_id,
                {"status": "failed", "error_message": str(ex)},
            )
        except Exception:
            pass
        raise


async def run_catalog_pull_job(job_id: str) -> None:
    """Ejecuta pull de catálogo en el proceso actual (sin cola Huey)."""
    try:
        await _catalog_pull_job_async(job_id)
    except Exception:
        logger.exception("catalog pull job %s failed", job_id)


async def run_catalog_push_job(job_id: str) -> None:
    """Ejecuta push de catálogo en el proceso actual (sin cola Huey)."""
    try:
        await _catalog_push_job_async(job_id)
    except Exception:
        logger.exception("catalog push job %s failed", job_id)


async def _catalog_pull_job_async(job_id: str) -> dict:
    logger.info("catalog pull job started job_id=%s", job_id)
    mysql = MySqlClient()
    if not mysql.is_configured():
        raise RuntimeError("MYSQL_* required for catalog pull job")
    hub = HubClient()
    path = job_file_path(job_id)
    save_job(
        job_id,
        {"job_id": job_id, "direction": "pull", "status": "running", "phase": "download"},
    )
    try:
        await report_progress(hub, job_id, phase="download", progress_nodo=5, force=True)
        await hub.download_sync_job_file(job_id, path)
        await report_progress(hub, job_id, phase="download", progress_nodo=40, force=True)

        result = await run_inventory_pull_from_file(
            file_path=path,
            hub=hub,
            mysql=mysql,
        )
        await report_progress(
            hub,
            job_id,
            phase="apply",
            progress_nodo=95,
            total_rows=result.get("pulled"),
            force=True,
        )
        delete_job_file(job_id)
        completed = await hub.patch_sync_job_progress(
            job_id,
            {"status": "completed", "result_summary": result, "progress_nodo": 100},
        )
        logger.info(
            "catalog pull job completed job_id=%s hub_status=%s pulled=%s",
            job_id,
            completed.get("status") if isinstance(completed, dict) else completed,
            result.get("pulled"),
        )
        save_job(job_id, {"job_id": job_id, "status": "completed", "result": result})
        return result
    except Exception as ex:
        delete_job_file(job_id)
        save_job(job_id, {"job_id": job_id, "status": "failed", "error": str(ex)})
        try:
            await hub.patch_sync_job_progress(
                job_id,
                {"status": "failed", "error_message": str(ex)},
            )
        except Exception:
            pass
        raise
