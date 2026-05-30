"""Push de categorías desde la tienda hacia el hub."""

from __future__ import annotations

from typing import Any

from catalog.compare import CATEGO_FIELDS
from db.mysql import MySqlClient
from hub.client import HubClient
from core.json_util import json_safe


def _hub_batch_stats(result: dict[str, Any]) -> dict[str, int]:
    """Acepta respuesta del hub en snake_case o camelCase."""
    return {
        "pulled": int(result.get("pulled") or 0),
        "inserted": int(result.get("inserted") or 0),
        "unchanged": int(result.get("unchanged") or 0),
        "conflicts": int(result.get("conflicts") or 0),
        "skipped": int(result.get("skipped") or 0),
        "warnings_reported": int(
            result.get("warnings_reported") or result.get("warningsReported") or 0
        ),
        "missing_dependencies": int(
            result.get("missing_dependencies")
            or result.get("missingDependencies")
            or 0
        ),
    }


def fetch_all_categorias(mysql: MySqlClient) -> list[dict[str, Any]]:
    col_list = ", ".join(CATEGO_FIELDS)

    def load():
        conn = mysql.connect()
        try:
            cur = conn.cursor(dictionary=True)
            cur.execute(
                f"""
                SELECT {col_list}
                FROM catego
                ORDER BY ccate ASC
                """
            )
            rows = [r for r in (cur.fetchall() or []) if isinstance(r, dict)]
            return [json_safe(r) for r in rows]
        finally:
            conn.close()

    return load()


async def run_category_push_to_hub(
    *,
    hub: HubClient,
    mysql: MySqlClient,
) -> dict[str, Any]:
    items = fetch_all_categorias(mysql)
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
        stats = _hub_batch_stats(await hub.push_categories_batch(chunk))
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
