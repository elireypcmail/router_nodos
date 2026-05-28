"""Pull de proveedores desde el hub con detección de conflictos."""

from __future__ import annotations

from typing import Any

from catalog_compare import sprv_diff_fields, sprv_snapshots_equal
from db_mysql import MySqlClient
from hub_client import HubClient
from pull_catalog_common import chunked, run_pull_with_compare
from pull_worker import pull_all_providers
from catalog_apply import apply_proveedor_row
from sprv_store import SPRV_BODY_FIELDS


def fetch_sprv_by_cod_prv(
    mysql: MySqlClient, codes: list[str]
) -> dict[str, dict[str, Any]]:
    codes = [c.strip() for c in codes if str(c or "").strip()]
    if not codes:
        return {}

    col_list = ", ".join(SPRV_BODY_FIELDS)

    def load():
        conn = mysql.connect()
        out: dict[str, dict[str, Any]] = {}
        try:
            cur = conn.cursor(dictionary=True)
            for chunk in chunked(codes, 400):
                placeholders = ", ".join(["%s"] * len(chunk))
                cur.execute(
                    f"""
                    SELECT {col_list}
                    FROM sprv
                    WHERE cod_prv IN ({placeholders})
                    """,
                    tuple(chunk),
                )
                for row in cur.fetchall() or []:
                    if isinstance(row, dict):
                        code = str(row.get("cod_prv") or "").strip()
                        if code:
                            out[code] = row
        finally:
            conn.close()
        return out

    return load()


async def run_provider_pull_from_hub(
    *,
    hub: HubClient,
    mysql: MySqlClient,
    page_size: int = 100,
) -> dict[str, Any]:
    items = await pull_all_providers(hub, page_size=page_size)
    if not items:
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

    import anyio

    inserted, unchanged, conflicts_count, conflicts, skipped = await anyio.to_thread.run_sync(
        lambda: run_pull_with_compare(
            mysql=mysql,
            hub_items=items,
            code_key="cod_prv",
            fetch_local=lambda codes: fetch_sprv_by_cod_prv(mysql, codes),
            snapshots_equal=sprv_snapshots_equal,
            diff_fields_fn=sprv_diff_fields,
            insert_row=apply_proveedor_row,
        )
    )

    reports = [
        {
            "direction": "pull",
            "entityType": "provider",
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
