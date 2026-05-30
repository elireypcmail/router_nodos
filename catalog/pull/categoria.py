"""Pull de categorías desde el hub con detección de conflictos."""

from __future__ import annotations

from typing import Any

from catalog.compare import (
    CATEGO_FIELDS,
    catego_diff_fields,
    catego_snapshots_equal,
)
from db.mysql import MySqlClient
from hub.client import HubClient
from catalog.pull_common import chunked, run_pull_with_compare
from sync.pull_worker import pull_all_categories
from catalog.apply import apply_categoria_row


def fetch_catego_by_ccates(
    mysql: MySqlClient, ccates: list[str]
) -> dict[str, dict[str, Any]]:
    ccates = [c.strip() for c in ccates if str(c or "").strip()]
    if not ccates:
        return {}

    col_list = ", ".join(CATEGO_FIELDS)

    def load():
        conn = mysql.connect()
        out: dict[str, dict[str, Any]] = {}
        try:
            cur = conn.cursor(dictionary=True)
            for chunk in chunked(ccates, 400):
                placeholders = ", ".join(["%s"] * len(chunk))
                cur.execute(
                    f"""
                    SELECT {col_list}
                    FROM catego
                    WHERE ccate IN ({placeholders})
                    """,
                    tuple(chunk),
                )
                for row in cur.fetchall() or []:
                    if isinstance(row, dict):
                        code = str(row.get("ccate") or "").strip()
                        if code:
                            out[code] = row
        finally:
            conn.close()
        return out

    return load()


async def run_category_pull_from_hub(
    *,
    hub: HubClient,
    mysql: MySqlClient,
    page_size: int = 100,
) -> dict[str, Any]:
    items = await pull_all_categories(hub, page_size=page_size)
    if not items:
        return _empty(page_size)

    import anyio

    inserted, unchanged, conflicts_count, conflicts, skipped = await anyio.to_thread.run_sync(
        lambda: run_pull_with_compare(
            mysql=mysql,
            hub_items=items,
            code_key="ccate",
            fetch_local=lambda codes: fetch_catego_by_ccates(mysql, codes),
            snapshots_equal=catego_snapshots_equal,
            diff_fields_fn=catego_diff_fields,
            insert_row=apply_categoria_row,
        )
    )

    reports = [
        {
            "direction": "pull",
            "entityType": "inventory_category",
            "warningType": "conflict",
            "codigo": c["codigo"],
            "hubSnapshot": c["hubSnapshot"],
            "nodeSnapshot": c["nodeSnapshot"],
            "diffFields": c["diffFields"],
        }
        for c in conflicts
    ]
    warnings_reported = 0
    if reports:
        warnings_reported = await hub.report_catalog_pull_warnings(reports)

    return {
        "pulled": len(items) - skipped,
        "inserted": inserted,
        "unchanged": unchanged,
        "conflicts": conflicts_count,
        "skipped": skipped,
        "warnings_reported": warnings_reported,
        "page_size": page_size,
        "message": "ok",
    }


def _empty(page_size: int) -> dict[str, Any]:
    return {
        "pulled": 0,
        "inserted": 0,
        "unchanged": 0,
        "conflicts": 0,
        "skipped": 0,
        "warnings_reported": 0,
        "page_size": page_size,
        "message": "ok",
    }
