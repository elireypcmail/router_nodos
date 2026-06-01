"""Procesa filas sync_outbox de catálogo (catego/sprv/sinv) → hub catalog-push por digest."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Protocol

import anyio

from catalog.compare import CATEGO_FIELDS
from outbox.digest import (
    CATALOG_TABLES,
    CatalogPushDigestStore,
    catalog_entity_key,
    compute_catalog_push_digest,
)
from db.mysql import MySqlClient
from core.json_util import json_safe
from catalog.push.inventario import DETALLE_PUSH_SELECT
from db.sprv_store import SPRV_BODY_FIELDS

SINV_PUSH_EXTRA_FIELDS = ("existencia", "costo", "costopro", "costoant")
DETALLE_PUSH_FIELDS = (
    "codigod",
    "lote",
    "cubica",
    "existencia",
    "vence",
    "elabora",
    "calidad",
    "costo",
    "costopro",
)

logger = logging.getLogger("multishop.outbox")

_SPRV_PUSH_FIELDS = SPRV_BODY_FIELDS


class CatalogHubPush(Protocol):
    async def push_categories_batch(self, items: list[dict]) -> dict: ...

    async def push_providers_batch(self, items: list[dict]) -> dict: ...

    async def push_inventory_batch(self, items: list[dict]) -> dict: ...


@dataclass
class CatalogOutboxSendResult:
    sent_ids: list[int] = field(default_factory=list)
    failed_ids: list[int] = field(default_factory=list)
    digest_skipped_ids: list[int] = field(default_factory=list)


def _catalog_code(table: str, pk: dict, row: dict) -> str | None:
    if table == "catego":
        return str(row.get("ccate") or pk.get("ccate") or "").strip() or None
    if table == "sprv":
        return str(row.get("cod_prv") or pk.get("cod_prv") or "").strip() or None
    if table == "sinv":
        return str(row.get("codigo") or pk.get("codigo") or "").strip() or None
    return None


def _load_catego_row(mysql: MySqlClient, ccate: str) -> dict[str, Any] | None:
    cols = ", ".join(CATEGO_FIELDS)

    def load() -> dict[str, Any] | None:
        conn = mysql.connect()
        try:
            cur = conn.cursor(dictionary=True)
            cur.execute(
                f"SELECT {cols} FROM catego WHERE ccate = %s LIMIT 1",
                (ccate,),
            )
            row = cur.fetchone()
            return json_safe(row) if isinstance(row, dict) else None
        finally:
            conn.close()

    return load()


def _load_sprv_row(mysql: MySqlClient, cod_prv: str) -> dict[str, Any] | None:
    cols = ", ".join(_SPRV_PUSH_FIELDS)

    def load() -> dict[str, Any] | None:
        conn = mysql.connect()
        try:
            cur = conn.cursor(dictionary=True)
            cur.execute(
                f"SELECT {cols} FROM sprv WHERE cod_prv = %s LIMIT 1",
                (cod_prv,),
            )
            row = cur.fetchone()
            return json_safe(row) if isinstance(row, dict) else None
        finally:
            conn.close()

    return load()


def _load_sinv_push_item(mysql: MySqlClient, codigo: str) -> dict[str, Any] | None:
    sinv_cols = ", ".join([*SINV_HUB_FIELDS, *SINV_PUSH_EXTRA_FIELDS])

    def load() -> dict[str, Any] | None:
        conn = mysql.connect()
        try:
            cur = conn.cursor(dictionary=True)
            cur.execute(
                f"SELECT {sinv_cols} FROM sinv WHERE codigo = %s LIMIT 1",
                (codigo,),
            )
            row = cur.fetchone()
            if not isinstance(row, dict):
                return None
            payload = json_safe(dict(row))
            cur.execute(
                f"""
                SELECT {DETALLE_PUSH_SELECT}
                FROM detalle d
                LEFT JOIN ubica u ON d.cubica = u.cubica
                WHERE d.codigo = %s
                ORDER BY d.cubica ASC, d.lote ASC, d.vence ASC
                """,
                (codigo,),
            )
            lotes = [
                json_safe(r)
                for r in (cur.fetchall() or [])
                if isinstance(r, dict)
            ]
            payload["lotes"] = lotes
            return payload
        finally:
            conn.close()

    return load()


def _load_push_item(
    mysql: MySqlClient,
    table: str,
    pk: dict[str, Any],
    row: dict[str, Any],
) -> dict[str, Any] | None:
    code = _catalog_code(table, pk, row)
    if not code:
        return None
    if table == "catego":
        return _load_catego_row(mysql, code)
    if table == "sprv":
        return _load_sprv_row(mysql, code)
    if table == "sinv":
        loaded = _load_sinv_push_item(mysql, code)
        if loaded is not None:
            return loaded
    return json_safe({**pk, **row})


def _dedupe_latest_by_entity(
    entries: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for raw in entries:
        table = str(raw.get("table") or "").strip().lower()
        if table not in CATALOG_TABLES:
            continue
        oid = int(raw.get("outbox_id") or 0)
        pk = raw.get("pk") if isinstance(raw.get("pk"), dict) else {}
        row = raw.get("row") if isinstance(raw.get("row"), dict) else {}
        item_preview = {**pk, **row}
        entity_key = catalog_entity_key(table, item_preview)
        if not entity_key:
            continue
        prev = latest.get(entity_key)
        if prev is None or oid >= int(prev.get("outbox_id") or 0):
            latest[entity_key] = raw
    return latest


async def send_catalog_outbox_batch(
    hub: CatalogHubPush,
    mysql: MySqlClient,
    batch: list[dict[str, Any]],
) -> CatalogOutboxSendResult:
    """Envía altas/cambios de catálogo al hub; omite si el digest no cambió."""

    if not mysql.is_configured():
        raise RuntimeError("MYSQL_* required for catalog outbox push")

    catalog_entries = [
        e
        for e in batch
        if str(e.get("table") or "").strip().lower() in CATALOG_TABLES
    ]
    if not catalog_entries:
        return CatalogOutboxSendResult()

    digest_store = CatalogPushDigestStore(mysql)
    await anyio.to_thread.run_sync(digest_store.ensure_schema)

    result = CatalogOutboxSendResult()
    latest = _dedupe_latest_by_entity(catalog_entries)

    to_push: dict[str, list[tuple[str, dict[str, Any], list[int]]]] = {
        "catego": [],
        "sprv": [],
        "sinv": [],
    }

    for entity_key, entry in latest.items():
        table = str(entry.get("table") or "").strip().lower()
        oid = int(entry.get("outbox_id") or 0)
        op = str(entry.get("op") or "I").strip().upper()
        pk = entry.get("pk") if isinstance(entry.get("pk"), dict) else {}
        row = entry.get("row") if isinstance(entry.get("row"), dict) else {}

        if op == "D":
            await anyio.to_thread.run_sync(digest_store.delete_digest, entity_key)
            result.sent_ids.append(oid)
            logger.info(
                "[catalog-outbox] delete %s outbox_id=%s (digest cleared)",
                entity_key,
                oid,
            )
            continue

        item = await anyio.to_thread.run_sync(
            _load_push_item, mysql, table, pk, row
        )
        if not item:
            result.failed_ids.append(oid)
            continue

        digest = compute_catalog_push_digest(table, item)
        prev = await anyio.to_thread.run_sync(digest_store.get_digest, entity_key)
        if prev == digest:
            result.digest_skipped_ids.append(oid)
            logger.debug(
                "[catalog-outbox] digest unchanged %s outbox_id=%s",
                entity_key,
                oid,
            )
            continue

        to_push[table].append((entity_key, item, [oid]))

    for table, rows in to_push.items():
        if not rows:
            continue
        items = [item for _, item, _ in rows]
        try:
            if table == "catego":
                await hub.push_categories_batch(items)
            elif table == "sprv":
                await hub.push_providers_batch(items)
            else:
                await hub.push_inventory_batch(items)
        except Exception as exc:
            for _, _, oids in rows:
                result.failed_ids.extend(oids)
            logger.warning(
                "[catalog-outbox] push %s failed (%s item(s)): %s",
                table,
                len(rows),
                exc,
            )
            continue

        for entity_key, item, oids in rows:
            digest = compute_catalog_push_digest(table, item)
            await anyio.to_thread.run_sync(
                digest_store.save_digest, entity_key, table, digest
            )
            result.sent_ids.extend(oids)
            logger.info(
                "[catalog-outbox] pushed %s outbox_id=%s digest=%s…",
                entity_key,
                oids[-1] if oids else "?",
                digest[:12],
            )

    return result
