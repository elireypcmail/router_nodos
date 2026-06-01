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
from sync.jobs.cancel import (
    JobCancelledError,
    ensure_hub_job_active,
    ensure_job_active,
    ensure_not_cancelled_sync,
)

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
                "attempts": e.attempts,
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


async def _finalize_cancelled_job(job_id: str, hub: HubClient) -> dict:
    delete_job_file(job_id)
    delete_job_file(f"{job_id}-purchase")
    delete_job_file(f"{job_id}-sale")
    save_job(
        job_id,
        {"job_id": job_id, "status": "cancelled", "message": "Cancelado desde admin"},
    )
    logger.info("catalog job %s cancelled cooperatively", job_id)
    return {"job_id": job_id, "status": "cancelled", "message": "ok"}


async def _catalog_transaction_mode_push_job_async(
    job_id: str,
    hub: HubClient,
    *,
    mode: str,
) -> dict:
    from sync.jobs.catalog_job_runner import fetch_hub_job_meta, resolve_transaction_since
    from sync.jobs.export_transactions import export_transaction_push_file

    phase = "compras" if mode == "purchase" else "ventas"
    job_meta = await fetch_hub_job_meta(hub, job_id)
    since_wm = resolve_transaction_since(job_meta, mode)
    mysql = MySqlClient()

    def on_export(done: int, total: int, pct: int) -> None:
        ensure_not_cancelled_sync(job_id)

        async def _report() -> None:
            await report_progress(
                hub,
                job_id,
                phase=phase,
                progress_nodo=pct,
                total_rows=total,
                processed_rows=done,
                force=(done == 0 or done == total or pct % 10 == 0),
            )

        anyio.from_thread.run(_report)

    await ensure_job_active(hub, job_id)
    path, file_rows, _export_meta = await anyio.to_thread.run_sync(
        lambda: export_transaction_push_file(
            job_id=job_id,
            mysql=mysql,
            nodo_id=settings.nodo_id,
            mode=mode,
            codigo=None,
            since_watermark=since_wm,
            should_cancel=lambda: ensure_not_cancelled_sync(job_id),
            on_progress=on_export,
        )
    )

    await report_progress(
        hub,
        job_id,
        phase="upload",
        progress_nodo=95,
        progress_hub=0,
        total_rows=int(file_rows or 0),
        processed_rows=0,
        force=True,
    )
    await hub.upload_sync_job_file(job_id, path)
    delete_job_file(job_id)
    await report_progress(
        hub,
        job_id,
        phase="process",
        progress_nodo=100,
        progress_hub=0,
        total_rows=int(file_rows or 0),
        processed_rows=0,
        force=True,
    )
    save_job(
        job_id,
        {
            "job_id": job_id,
            "direction": "push",
            "status": "uploaded",
            "phase": "process",
            "mode": mode,
            "file_rows": file_rows,
        },
    )
    return {
        "job_id": job_id,
        "status": "uploaded",
        "mode": mode,
        "total_rows": int(file_rows or 0),
    }


async def _catalog_push_job_async(job_id: str) -> dict:
    mysql = MySqlClient()
    if not mysql.is_configured():
        raise RuntimeError("MYSQL_* required for catalog push job")
    hub = HubClient()
    from sync.jobs.catalog_job_runner import fetch_hub_job_meta, resolve_job_entity_type

    job_meta = await fetch_hub_job_meta(hub, job_id)
    entity = resolve_job_entity_type(job_meta)

    from sync.jobs.catalog_job_runner import resolve_transaction_mode_from_entity

    txn_mode = resolve_transaction_mode_from_entity(entity)
    if txn_mode:
        phase = "compras" if txn_mode == "purchase" else "ventas"
        save_job(
            job_id,
            {
                "job_id": job_id,
                "direction": "push",
                "entity_type": entity,
                "status": "running",
                "phase": phase,
            },
        )
        try:
            return await _catalog_transaction_mode_push_job_async(
                job_id, hub, mode=txn_mode
            )
        except JobCancelledError:
            return await _finalize_cancelled_job(job_id, hub)
        except Exception as ex:
            save_job(job_id, {"job_id": job_id, "status": "failed", "error": str(ex)})
            try:
                await hub.patch_sync_job_progress(
                    job_id,
                    {"status": "failed", "error_message": str(ex)},
                )
            except Exception:
                pass
            raise

    save_job(
        job_id,
        {
            "job_id": job_id,
            "direction": "push",
            "entity_type": entity,
            "status": "running",
            "phase": "export",
        },
    )

    def on_export(done: int, total: int, pct: int) -> None:
        ensure_not_cancelled_sync(job_id)

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

    cancel_check = lambda: ensure_not_cancelled_sync(job_id)

    try:
        if entity == "inventory_category":
            from sync.jobs.export_catalog import export_category_push_file

            export_fn = export_category_push_file
        elif entity == "provider":
            from sync.jobs.export_catalog import export_provider_push_file

            export_fn = export_provider_push_file
        else:
            export_fn = export_inventory_push_file

        path, total = await anyio.to_thread.run_sync(
            lambda: export_fn(
                job_id,
                mysql,
                settings.nodo_id,
                on_progress=on_export,
                should_cancel=cancel_check,
            )
        )
        await ensure_hub_job_active(hub, job_id)
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
    except JobCancelledError:
        return await _finalize_cancelled_job(job_id, hub)
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
    except JobCancelledError:
        logger.info("catalog pull job %s cancelled", job_id)
    except Exception:
        logger.exception("catalog pull job %s failed", job_id)


async def run_catalog_push_job(job_id: str) -> None:
    """Ejecuta push de catálogo en el proceso actual (sin cola Huey)."""
    try:
        await _catalog_push_job_async(job_id)
    except JobCancelledError:
        logger.info("catalog push job %s cancelled", job_id)
    except Exception:
        logger.exception("catalog push job %s failed", job_id)


async def _catalog_pull_job_async(job_id: str) -> dict:
    logger.info("catalog pull job started job_id=%s", job_id)
    mysql = MySqlClient()
    if not mysql.is_configured():
        raise RuntimeError("MYSQL_* required for catalog pull job")
    hub = HubClient()
    from sync.jobs.catalog_job_runner import fetch_hub_job_meta, resolve_job_entity_type
    from sync.jobs.pull_catalog import (
        run_category_pull_from_file,
        run_provider_pull_from_file,
    )

    job_meta = await fetch_hub_job_meta(hub, job_id)
    entity = resolve_job_entity_type(job_meta)
    path = job_file_path(job_id)
    save_job(
        job_id,
        {
            "job_id": job_id,
            "direction": "pull",
            "entity_type": entity,
            "status": "running",
            "phase": "download",
        },
    )
    try:
        await ensure_job_active(hub, job_id)
        await report_progress(hub, job_id, phase="download", progress_nodo=5, force=True)
        await hub.download_sync_job_file(job_id, path)
        await ensure_job_active(hub, job_id)
        await report_progress(hub, job_id, phase="download", progress_nodo=40, force=True)

        if entity == "inventory_category":
            result = await run_category_pull_from_file(
                file_path=path,
                hub=hub,
                mysql=mysql,
            )
        elif entity == "provider":
            result = await run_provider_pull_from_file(
                file_path=path,
                hub=hub,
                mysql=mysql,
            )
        else:
            result = await run_inventory_pull_from_file(
                file_path=path,
                hub=hub,
                mysql=mysql,
            )
        await ensure_hub_job_active(hub, job_id)
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
            "catalog pull job completed job_id=%s entity=%s hub_status=%s pulled=%s",
            job_id,
            entity,
            completed.get("status") if isinstance(completed, dict) else completed,
            result.get("pulled"),
        )
        save_job(job_id, {"job_id": job_id, "status": "completed", "result": result})
        return result
    except JobCancelledError:
        return await _finalize_cancelled_job(job_id, hub)
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
