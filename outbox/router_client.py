"""Envía eventos outbox al router Nest (webhooks por API key del tenant)."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from core.config import settings
from core.json_util import json_safe
from db.mysql import MySqlClient
from outbox.catalog_enrich import enrich_catalog_row
from outbox.catalog_tables import (
    CATALOG_OUTBOX_TABLES,
    catalog_entity_type,
    catalog_event_name,
)
from outbox.movement_tables import (
    ALL_MOVEMENT_OUTBOX_TABLES,
    normalize_source_table,
    resolve_entity_type,
)
from outbox.mysql import OutboxEvent
from outbox.movement_enrich import MovementEnrichmentError, enrich_movement_row
from outbox.send_result import OutboxSendResult

logger = logging.getLogger(__name__)


def build_router_event_payload(event: OutboxEvent) -> dict[str, Any]:
    row = event.row if isinstance(event.row, dict) else None
    occurred_at = event.created_at or datetime.now(timezone.utc).isoformat()

    if event.table_name in CATALOG_OUTBOX_TABLES:
        event_name = catalog_event_name(event.table_name)
        if not event_name:
            raise ValueError(f"unknown catalog table={event.table_name!r}")
        return {
            "event": event_name,
            "occurredAt": occurred_at,
            "eventId": event.event_id,
            "entityType": catalog_entity_type(event.table_name),
            "sourceTable": event.table_name,
            "operation": event.op,
            "primaryKey": event.pk,
            "row": event.row,
            "outboxId": event.id,
        }

    entity_type = resolve_entity_type(event.table_name, row)
    return {
        "event": "kardex.change",
        "occurredAt": occurred_at,
        "eventId": event.event_id,
        "entityType": entity_type,
        "sourceTable": normalize_source_table(event.table_name),
        "operation": event.op,
        "primaryKey": event.pk,
        "row": event.row,
        "outboxId": event.id,
    }


def post_event_to_router(payload: dict[str, Any]) -> None:
    base = (settings.router_events_url or "").strip().rstrip("/")
    if not base:
        raise RuntimeError("ROUTER_EVENTS_URL no configurada")
    url = f"{base}/internal/nodos/events"
    body = json.dumps(json_safe(payload)).encode("utf-8")
    token = (settings.nodo_api_token or "").strip()
    req = Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "Multishop-Nodo-Outbox/1.0",
        },
    )
    with urlopen(req, timeout=15) as res:
        if res.status >= 400:
            raise HTTPError(url, res.status, res.reason, res.headers, None)


def send_outbox_batch(events: list[OutboxEvent]) -> OutboxSendResult:
    sent_ids: list[int] = []
    ignored_ids: list[int] = []
    failed_ids: list[int] = []
    failed_messages: dict[int, str] = {}
    mysql = MySqlClient()

    for event in events:
        is_movement = event.table_name in ALL_MOVEMENT_OUTBOX_TABLES
        is_catalog = event.table_name in CATALOG_OUTBOX_TABLES
        if not is_movement and not is_catalog:
            ignored_ids.append(event.id)
            continue
        if is_catalog and event.op == "D":
            ignored_ids.append(event.id)
            continue
        try:
            payload = build_router_event_payload(event)
            row = payload.get("row")
            if isinstance(row, dict) or row is None:
                if is_catalog:
                    payload["row"] = enrich_catalog_row(
                        event.table_name,
                        row if isinstance(row, dict) else None,
                        event.pk if isinstance(event.pk, dict) else None,
                        mysql,
                    )
                elif isinstance(row, dict):
                    payload["row"] = enrich_movement_row(
                        event.table_name,
                        row,
                        event.pk,
                        mysql,
                    )
            post_event_to_router(payload)
            sent_ids.append(event.id)
        except MovementEnrichmentError as exc:
            failed_ids.append(event.id)
            failed_messages[event.id] = str(exc)[:2000]
            logger.warning("outbox %s enriquecimiento pendiente: %s", event.id, exc)
        except (HTTPError, URLError, RuntimeError, OSError, ValueError) as exc:
            failed_ids.append(event.id)
            failed_messages[event.id] = str(exc)[:2000]
            logger.warning("outbox %s no reenviado: %s", event.id, exc)

    return OutboxSendResult(
        sent_ids=sent_ids,
        ignored_ids=ignored_ids,
        failed_ids=failed_ids,
        failed_messages=failed_messages,
    )
