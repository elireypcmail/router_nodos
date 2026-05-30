"""Push de proveedores desde la tienda hacia el hub."""

from __future__ import annotations

from typing import Any

from db.mysql import MySqlClient
from hub.client import HubClient
from core.json_util import json_safe
from catalog.push.categoria import _hub_batch_stats
from db.sprv_store import SPRV_BODY_FIELDS


def fetch_all_proveedores(mysql: MySqlClient) -> list[dict[str, Any]]:
    col_list = ", ".join(SPRV_BODY_FIELDS)

    def load():
        conn = mysql.connect()
        try:
            cur = conn.cursor(dictionary=True)
            cur.execute(
                f"""
                SELECT {col_list}
                FROM sprv
                ORDER BY cod_prv ASC
                """
            )
            rows = [r for r in (cur.fetchall() or []) if isinstance(r, dict)]
            return [json_safe(r) for r in rows]
        finally:
            conn.close()

    return load()


async def run_provider_push_to_hub(
    *,
    hub: HubClient,
    mysql: MySqlClient,
) -> dict[str, Any]:
    items = fetch_all_proveedores(mysql)
    if not items:
        return {
            "pulled": 0,
            "inserted": 0,
            "unchanged": 0,
            "conflicts": 0,
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

    chunk_size = 100
    for i in range(0, len(items), chunk_size):
        chunk = items[i : i + chunk_size]
        stats = _hub_batch_stats(await hub.push_providers_batch(chunk))
        pulled += stats["pulled"]
        inserted += stats["inserted"]
        unchanged += stats["unchanged"]
        conflicts += stats["conflicts"]
        missing_dependencies += stats["missing_dependencies"]
        skipped += stats["skipped"]
        warnings_reported += stats["warnings_reported"]

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
