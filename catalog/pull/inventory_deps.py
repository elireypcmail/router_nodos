"""Category/provider dependencies when pulling inventory from hub to store."""

from __future__ import annotations

from typing import Any

from catalog.apply import apply_categoria_row, apply_proveedor_row
from hub.client import HubClient
from catalog.pull_common import fetch_codes_existing


def inventory_missing_refs(
    hub_row: dict,
    *,
    local_ccates: set[str],
    local_prv: set[str],
    hub_catego: dict[str, dict] | None = None,
    hub_prv: dict[str, dict] | None = None,
) -> dict[str, Any] | None:
    ccate = str(hub_row.get("ccate") or "").strip()
    cod_prv = str(hub_row.get("cod_prv") or "").strip()
    hub_catego = hub_catego or {}
    hub_prv = hub_prv or {}

    missing_category = bool(ccate) and ccate not in local_ccates and ccate not in hub_catego
    missing_provider = bool(cod_prv) and cod_prv not in local_prv and cod_prv not in hub_prv
    if not missing_category and not missing_provider:
        return None
    return {
        "ccate": ccate,
        "cod_prv": cod_prv,
        "missingCategory": missing_category,
        "missingProvider": missing_provider,
    }


def collect_missing_dep_codes(
    hub_by_codigo: dict[str, dict],
    local_ccates: set[str],
    local_prv: set[str],
) -> tuple[set[str], set[str]]:
    missing_ccates: set[str] = set()
    missing_prvs: set[str] = set()
    for hub_row in hub_by_codigo.values():
        refs = inventory_missing_refs(
            hub_row,
            local_ccates=local_ccates,
            local_prv=local_prv,
        )
        if not refs:
            continue
        if refs.get("missingCategory"):
            ccate = str(refs.get("ccate") or "").strip()
            if ccate:
                missing_ccates.add(ccate)
        if refs.get("missingProvider"):
            cod_prv = str(refs.get("cod_prv") or "").strip()
            if cod_prv:
                missing_prvs.add(cod_prv)
    return missing_ccates, missing_prvs


async def fetch_hub_dependency_rows(
    hub: HubClient,
    ccates: set[str],
    cod_prvs: set[str],
) -> tuple[dict[str, dict], dict[str, dict]]:
    """Filas del hub para upsert local de catego/sprv antes de sinv."""
    categoria_rows: dict[str, dict] = {}
    proveedor_rows: dict[str, dict] = {}

    for ccate in sorted(ccates):
        row = await hub.get_categoria_in_hub(ccate)
        if isinstance(row, dict):
            categoria_rows[ccate] = row

    for cod_prv in sorted(cod_prvs):
        row = await hub.get_proveedor_in_hub(cod_prv)
        if isinstance(row, dict):
            proveedor_rows[cod_prv] = row

    return categoria_rows, proveedor_rows


def apply_inventory_row_dependencies(
    cur,
    hub_row: dict,
    *,
    hub_catego: dict[str, dict],
    hub_prv: dict[str, dict],
    local_ccates: set[str],
    local_prv: set[str],
) -> None:
    """Upsert categoría/proveedor del hub en la misma transacción que sinv."""
    ccate = str(hub_row.get("ccate") or "").strip()
    cod_prv = str(hub_row.get("cod_prv") or "").strip()

    if ccate and ccate not in local_ccates:
        cat_row = hub_catego.get(ccate)
        if cat_row:
            apply_categoria_row(cur, cat_row)
            local_ccates.add(ccate)

    if cod_prv and cod_prv not in local_prv:
        prv_row = hub_prv.get(cod_prv)
        if prv_row:
            apply_proveedor_row(cur, prv_row)
            local_prv.add(cod_prv)


async def fetch_row_dependencies_from_hub(
    hub: HubClient,
    mysql,
    hub_row: dict,
) -> tuple[dict[str, dict], dict[str, dict]]:
    """Categoría/proveedor del hub que faltan en MySQL local para una fila sinv."""
    ccate = str(hub_row.get("ccate") or "").strip()
    cod_prv = str(hub_row.get("cod_prv") or "").strip()
    if not ccate and not cod_prv:
        return {}, {}

    local_ccates = fetch_codes_existing(
        mysql, "catego", "ccate", [ccate] if ccate else []
    )
    local_prv = fetch_codes_existing(
        mysql, "sprv", "cod_prv", [cod_prv] if cod_prv else []
    )
    missing_ccates: set[str] = set()
    missing_prvs: set[str] = set()
    if ccate and ccate not in local_ccates:
        missing_ccates.add(ccate)
    if cod_prv and cod_prv not in local_prv:
        missing_prvs.add(cod_prv)
    if not missing_ccates and not missing_prvs:
        return {}, {}
    return await fetch_hub_dependency_rows(hub, missing_ccates, missing_prvs)

