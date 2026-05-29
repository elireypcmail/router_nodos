from __future__ import annotations

import logging
from typing import Any

import anyio

from config import settings
from log_compat import configure_node_logging, ascii_safe
from db_mysql import MySqlClient
from hub_client import HubClient
from huey_app import huey
from outbox_mysql import OutboxRepository
from sync_job_export import export_inventory_push_file
from sync_job_files import delete_job_file, job_file_path
from sync_job_progress import report_progress
from sync_job_pull_file import run_inventory_pull_from_file
from sync_job_store import save_job

logger = logging.getLogger("multishop.outbox")

configure_node_logging()

@huey.task(retries=settings.huey_outbox_task_retries, retry_delay=settings.huey_outbox_retry_delay_seconds)
def send_outbox_batch() -> dict[str, Any]:
    """Huey task: reserve a pending outbox batch and send it to the hub."""
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
        return {"sent": 0, "message": "no_pending"}

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


@huey.task()
def enqueue_outbox() -> None:
    try:
        send_outbox_batch()
    finally:
        # SqliteHuey (huey 2.x): use TaskWrapper.schedule(), not huey.enqueue_in().
        delay_sec = max(
            1, int(float(settings.huey_outbox_enqueue_interval_seconds))
        )
        enqueue_outbox.schedule(delay=delay_sec)


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
        anyio.from_thread.run(
            report_progress,
            hub,
            job_id,
            phase="export",
            progress_nodo=pct,
            total_rows=total,
            processed_rows=done,
        )

    try:
        path, total = await anyio.to_thread.run_sync(
            export_inventory_push_file,
            job_id,
            mysql,
            settings.nodo_id,
            on_progress=on_export,
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
            phase="upload",
            progress_nodo=90,
            total_rows=total,
            force=True,
        )
        save_job(
            job_id,
            {"job_id": job_id, "direction": "push", "status": "running", "phase": "process"},
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


async def _catalog_pull_job_async(job_id: str) -> dict:
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
        await hub.patch_sync_job_progress(
            job_id,
            {"status": "completed", "result_summary": result, "progress_nodo": 100},
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
