from __future__ import annotations

import logging
from typing import Any

from core.config import settings
from core.log_compat import ascii_safe, configure_node_logging
from db.mysql import MySqlClient
from outbox.mysql import OutboxRepository
from outbox.router_client import send_outbox_batch
from workers.huey_app import huey

logger = logging.getLogger("multishop.outbox")

configure_node_logging()

_OUTBOX_PRIORITY = 0


def run_outbox_flush_once() -> dict[str, Any]:
    mysql = MySqlClient()
    if not mysql.is_configured():
        raise RuntimeError("Huey outbox requires MYSQL_* configured")
    if not (settings.router_events_url or "").strip():
        return {"sent": 0, "ignored": 0, "failed": 0, "message": "router_events_url_missing"}

    repo = OutboxRepository(mysql)
    repo.ensure_schema()
    recovered = repo.recover_processing()
    if recovered:
        logger.warning("Outbox: recovered %s row(s) from processing", recovered)

    events = repo.reserve_pending(limit=int(settings.huey_outbox_batch_size))
    if not events:
        return {"sent": 0, "ignored": 0, "failed": 0, "message": "no_pending"}

    try:
        result = send_outbox_batch(events)
        repo.apply_send_result(result)
        return {
            "sent": len(result.sent_ids),
            "ignored": len(result.ignored_ids),
            "failed": len(result.failed_ids),
            "message": "ok" if not result.has_failures else "partial_failure",
        }
    except Exception as ex:
        ids = [e.id for e in events]
        repo.release_to_pending(ids, ascii_safe(ex))
        raise


@huey.task()
def outbox_tick() -> dict[str, Any]:
    try:
        return run_outbox_flush_once()
    finally:
        delay_sec = max(1, int(float(settings.huey_outbox_enqueue_interval_seconds)))
        outbox_tick.schedule(delay=delay_sec, priority=_OUTBOX_PRIORITY)


def bootstrap_outbox_scheduler() -> None:
    huey.storage.flush_schedule()
    outbox_tick.schedule(delay=0, priority=_OUTBOX_PRIORITY)
    logger.info("Outbox Huey: outbox_tick programado")
