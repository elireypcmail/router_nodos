"""Push de inventario (sinv + existencia, costos y lotes) desde la tienda hacia el hub."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from db.mysql import MySqlClient
from hub.client import HubClient
from core.json_util import json_safe
from catalog.push.categoria import _hub_batch_stats
from db.sinv_store import SINV_HUB_FIELDS

SINV_PUSH_EXTRA_FIELDS = ("existencia", "costo", "costopro", "costoant")

DETALLE_PUSH_FIELDS = (
    "lote",
    "cubica",
    "existencia",
    "vence",
    "elabora",
    "calidad",
    "costo",
    "costopro",
)


def _fetch_detalle_by_codigo(mysql: MySqlClient) -> dict[str, list[dict[str, Any]]]:
    col_list = ", ".join(("codigo", *DETALLE_PUSH_FIELDS))

    def load():
        conn = mysql.connect()
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        try:
            cur = conn.cursor(dictionary=True)
            cur.execute(
                f"""
                SELECT {col_list}
                FROM detalle
                ORDER BY codigo ASC, cubica ASC, lote ASC, vence ASC
                """
            )
            for row in cur.fetchall() or []:
                if not isinstance(row, dict):
                    continue
                codigo = str(row.get("codigo") or "").strip()
                if not codigo:
                    continue
                grouped[codigo].append(json_safe(row))
        finally:
            conn.close()
        return dict(grouped)

    return load()


def fetch_all_inventario_push(mysql: MySqlClient) -> list[dict[str, Any]]:
    sinv_cols = ", ".join([*SINV_HUB_FIELDS, *SINV_PUSH_EXTRA_FIELDS])
    detalle_map = _fetch_detalle_by_codigo(mysql)

    def load():
        conn = mysql.connect()
        try:
            cur = conn.cursor(dictionary=True)
            cur.execute(
                f"""
                SELECT {sinv_cols}
                FROM sinv
                ORDER BY codigo ASC
                """
            )
            out: list[dict[str, Any]] = []
            for row in cur.fetchall() or []:
                if not isinstance(row, dict):
                    continue
                codigo = str(row.get("codigo") or "").strip()
                if not codigo:
                    continue
                payload = json_safe(dict(row))
                payload["lotes"] = detalle_map.get(codigo, [])
                out.append(payload)
            return out
        finally:
            conn.close()

    return load()


async def run_inventory_push_to_hub(
    *,
    hub: HubClient,
    mysql: MySqlClient,
) -> dict[str, Any]:
    items = fetch_all_inventario_push(mysql)
    if not items:
        return {
            "pulled": 0,
            "inserted": 0,
            "unchanged": 0,
            "conflicts": 0,
            "missing_dependencies": 0,
            "skipped": 0,
            "warnings_reported": 0,
            "message": "ok",
        }

    inserted = 0
    unchanged = 0
    conflicts = 0
    missing_dependencies = 0
    skipped = 0
    warnings_reported = 0
    pulled = 0

    chunk_size = 50
    for i in range(0, len(items), chunk_size):
        chunk = items[i : i + chunk_size]
        stats = _hub_batch_stats(await hub.push_inventory_batch(chunk))
        pulled += stats["pulled"]
        inserted += stats["inserted"]
        unchanged += stats["unchanged"]
        conflicts += stats["conflicts"]
        skipped += stats["skipped"]
        warnings_reported += stats["warnings_reported"]
        missing_dependencies += stats["missing_dependencies"]

    if pulled == 0 and len(items) > 0:
        pulled = len(items)

    return {
        "pulled": pulled,
        "inserted": inserted,
        "unchanged": unchanged,
        "conflicts": conflicts,
        "missing_dependencies": missing_dependencies,
        "skipped": skipped,
        "warnings_reported": warnings_reported,
        "message": "ok",
    }
