"""Pull de inventario desde el hub con conflictos y validación de dependencias."""

from __future__ import annotations

from typing import Any

from db_mysql import MySqlClient
from hub_client import HubClient
from pull_catalog_common import fetch_codes_existing
from pull_worker import pull_all_products
from sinv_compare import sinv_diff_fields, sinv_snapshots_equal
from sinv_store import SINV_HUB_FIELDS, upsert_sinv
from pull_catalog_common import chunked


def fetch_sinv_snapshots_by_codigos(
    mysql: MySqlClient, codigos: list[str]
) -> dict[str, dict[str, Any]]:
    codigos = [c.strip() for c in codigos if str(c or "").strip()]
    if not codigos:
        return {}

    col_list = ", ".join(SINV_HUB_FIELDS)

    def load():
        conn = mysql.connect()
        out: dict[str, dict[str, Any]] = {}
        try:
            cur = conn.cursor(dictionary=True)
            for chunk in chunked(codigos, 400):
                placeholders = ", ".join(["%s"] * len(chunk))
                cur.execute(
                    f"""
                    SELECT {col_list}
                    FROM sinv
                    WHERE codigo IN ({placeholders})
                    """,
                    tuple(chunk),
                )
                for row in cur.fetchall() or []:
                    if isinstance(row, dict):
                        code = str(row.get("codigo") or "").strip()
                        if code:
                            out[code] = row
        finally:
            conn.close()
        return out

    return load()


def _inventory_missing_refs(
    hub_row: dict,
    *,
    local_ccates: set[str],
    local_prv: set[str],
) -> dict[str, Any] | None:
    ccate = str(hub_row.get("ccate") or "").strip()
    cod_prv = str(hub_row.get("cod_prv") or "").strip()
    missing_category = bool(ccate) and ccate not in local_ccates
    missing_provider = bool(cod_prv) and cod_prv not in local_prv
    if not missing_category and not missing_provider:
        return None
    return {
        "ccate": ccate,
        "cod_prv": cod_prv,
        "missingCategory": missing_category,
        "missingProvider": missing_provider,
    }


async def run_inventory_pull_from_hub(
    *,
    hub: HubClient,
    mysql: MySqlClient,
    page_size: int = 100,
) -> dict[str, Any]:
    items = await pull_all_products(hub, page_size=page_size)
    if not items:
        return {
            "pulled": 0,
            "inserted": 0,
            "unchanged": 0,
            "conflicts": 0,
            "missing_dependencies": 0,
            "skipped": 0,
            "warnings_reported": 0,
            "page_size": page_size,
            "message": "ok",
        }

    hub_by_codigo: dict[str, dict] = {}
    skipped = 0
    all_ccates: list[str] = []
    all_prv: list[str] = []
    for it in items:
        if not isinstance(it, dict):
            skipped += 1
            continue
        codigo = str(it.get("codigo") or "").strip()
        if not codigo:
            skipped += 1
            continue
        hub_by_codigo[codigo] = it
        ccate = str(it.get("ccate") or "").strip()
        cod_prv = str(it.get("cod_prv") or "").strip()
        if ccate:
            all_ccates.append(ccate)
        if cod_prv:
            all_prv.append(cod_prv)

    def process():
        local_sinv = fetch_sinv_snapshots_by_codigos(mysql, list(hub_by_codigo.keys()))
        local_ccates = fetch_codes_existing(mysql, "catego", "ccate", all_ccates)
        local_prv = fetch_codes_existing(mysql, "sprv", "cod_prv", all_prv)

        to_insert: list[dict] = []
        conflicts: list[dict] = []
        missing_deps: list[dict] = []
        unchanged = 0

        for codigo, hub_row in hub_by_codigo.items():
            missing = _inventory_missing_refs(
                hub_row,
                local_ccates=local_ccates,
                local_prv=local_prv,
            )
            if missing:
                missing_deps.append(
                    {
                        "direction": "pull",
                        "entityType": "inventory",
                        "warningType": "missing_dependency",
                        "codigo": codigo,
                        "hubSnapshot": hub_row,
                        "nodeSnapshot": None,
                        "diffFields": [],
                        "missingRefs": missing,
                    }
                )
                continue

            node_row = local_sinv.get(codigo)
            if node_row is None:
                to_insert.append(hub_row)
                continue
            if sinv_snapshots_equal(hub_row, node_row):
                unchanged += 1
                continue
            conflicts.append(
                {
                    "direction": "pull",
                    "entityType": "inventory",
                    "warningType": "conflict",
                    "codigo": codigo,
                    "hubSnapshot": hub_row,
                    "nodeSnapshot": node_row,
                    "diffFields": sinv_diff_fields(hub_row, node_row),
                }
            )

        inserted = 0
        if to_insert:
            conn = mysql.connect()
            try:
                cur = conn.cursor()
                for row in to_insert:
                    upsert_sinv(cur, row)
                    inserted += 1
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

        return inserted, unchanged, conflicts, missing_deps

    import anyio

    inserted, unchanged, conflicts, missing_deps = await anyio.to_thread.run_sync(
        process
    )

    reports = conflicts + missing_deps
    warnings_reported = 0
    if reports:
        warnings_reported = await hub.report_catalog_pull_warnings(reports)

    return {
        "pulled": len(hub_by_codigo),
        "inserted": inserted,
        "unchanged": unchanged,
        "conflicts": len(conflicts),
        "missing_dependencies": len(missing_deps),
        "skipped": skipped,
        "warnings_reported": warnings_reported,
        "page_size": page_size,
        "message": "ok",
    }
