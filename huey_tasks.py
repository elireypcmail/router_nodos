from __future__ import annotations

from datetime import timedelta
from typing import Any

from config import settings
from hub_client import HubClient
from huey_app import huey
from outbox_mysql import OutboxRepository
from db_mysql import MySqlClient


@huey.task(retries=settings.huey_outbox_task_retries, retry_delay=settings.huey_outbox_retry_delay_seconds)
def send_outbox_batch() -> dict[str, Any]:
    """Tarea Huey: reserva un batch de eventos pending y los envía al hub.

    Si falla por conectividad/HTTP, Huey reintenta. Los eventos se devuelven a
    pending en cada fallo para que vuelvan a ser elegibles.
    """
    mysql = MySqlClient()
    if not mysql.is_configured():
        raise RuntimeError("Huey outbox requires MYSQL_* configured")

    repo = OutboxRepository(mysql)
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
        import anyio

        anyio.run(hub.send_outbox_batch, payload)
        repo.mark_sent(ids)
        return {"sent": len(ids), "message": "ok"}
    except Exception as ex:
        repo.release_to_pending(ids, str(ex))
        raise


@huey.task()
def enqueue_outbox() -> None:
    send_outbox_batch()
    huey.enqueue_in(
        timedelta(seconds=float(settings.huey_outbox_enqueue_interval_seconds)),
        enqueue_outbox,
    )
