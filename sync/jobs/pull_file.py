from __future__ import annotations

from pathlib import Path
from typing import Any

import anyio

from db.mysql import MySqlClient
from hub.client import HubClient
from catalog.pull_common import fetch_codes_existing
from catalog.pull.inventario import _process_inventory_pull
from catalog.pull.inventory_deps import collect_missing_dep_codes, fetch_hub_dependency_rows
from sync.jobs.export import iter_inventory_rows_from_gz


async def run_inventory_pull_from_file(
    *,
    file_path: Path,
    hub: HubClient,
    mysql: MySqlClient,
    on_progress=None,
) -> dict[str, Any]:
    items: list[dict[str, Any]] = list(iter_inventory_rows_from_gz(file_path))
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

    def scan_missing_codes():
        local_ccates = fetch_codes_existing(mysql, "catego", "ccate", all_ccates)
        local_prv = fetch_codes_existing(mysql, "sprv", "cod_prv", all_prv)
        return collect_missing_dep_codes(hub_by_codigo, local_ccates, local_prv)

    missing_ccates, missing_prvs = await anyio.to_thread.run_sync(scan_missing_codes)
    hub_catego, hub_prv = await fetch_hub_dependency_rows(
        hub, missing_ccates, missing_prvs
    )

    inserted, patched, unchanged, conflicts, missing_deps = await anyio.to_thread.run_sync(
        lambda: _process_inventory_pull(
            mysql,
            hub_by_codigo,
            hub_catego=hub_catego,
            hub_prv=hub_prv,
        )
    )

    reports = conflicts + missing_deps
    warnings_reported = 0
    if reports:
        warnings_reported = await hub.report_catalog_pull_warnings(reports)

    total = len(hub_by_codigo)
    if on_progress:
        on_progress(total, total, 100)

    return {
        "pulled": total,
        "inserted": inserted,
        "patched": patched,
        "unchanged": unchanged,
        "conflicts": len(conflicts),
        "missing_dependencies": len(missing_deps),
        "skipped": skipped,
        "warnings_reported": warnings_reported,
        "message": "ok",
    }
