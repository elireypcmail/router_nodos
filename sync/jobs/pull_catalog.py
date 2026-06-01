from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Any

import anyio

from catalog.apply import apply_categoria_row, apply_proveedor_row
from catalog.compare import (
    catego_diff_fields,
    catego_snapshots_equal,
    sprv_diff_fields,
    sprv_snapshots_equal,
)
from catalog.pull.categoria import fetch_catego_by_ccates
from catalog.pull.proveedor import fetch_sprv_by_cod_prv
from catalog.pull_common import run_pull_with_compare
from db.mysql import MySqlClient
from hub.client import HubClient


def _iter_rows_from_gz(path: Path) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    with gzip.open(path, "rt", encoding="utf-8") as gz:
        first = True
        for line in gz:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if first:
                first = False
                continue
            if isinstance(row, dict):
                items.append(row)
    return items


async def run_category_pull_from_file(
    *,
    file_path: Path,
    hub: HubClient,
    mysql: MySqlClient,
    on_progress=None,
) -> dict[str, Any]:
    items = _iter_rows_from_gz(file_path)
    if not items:
        return _empty_pull()

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

    total = len(items) - skipped
    if on_progress:
        on_progress(total, total, 100)

    return {
        "pulled": total,
        "inserted": inserted,
        "unchanged": unchanged,
        "conflicts": conflicts_count,
        "skipped": skipped,
        "warnings_reported": warnings_reported,
        "message": "ok",
    }


async def run_provider_pull_from_file(
    *,
    file_path: Path,
    hub: HubClient,
    mysql: MySqlClient,
    on_progress=None,
) -> dict[str, Any]:
    items = _iter_rows_from_gz(file_path)
    if not items:
        return _empty_pull()

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

    total = len(items) - skipped
    if on_progress:
        on_progress(total, total, 100)

    return {
        "pulled": total,
        "inserted": inserted,
        "unchanged": unchanged,
        "conflicts": conflicts_count,
        "skipped": skipped,
        "warnings_reported": warnings_reported,
        "message": "ok",
    }


def _empty_pull() -> dict[str, Any]:
    return {
        "pulled": 0,
        "inserted": 0,
        "unchanged": 0,
        "conflicts": 0,
        "skipped": 0,
        "warnings_reported": 0,
        "message": "ok",
    }
