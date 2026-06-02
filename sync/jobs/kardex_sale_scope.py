"""Filtros kardex (ventas) compartidos entre export .ndjson.gz e índice diariovi/ventasi."""

from __future__ import annotations

from typing import Any

from db.schema_cache import TableColumnCache
from sync.jobs.transaction_sync_types import TransactionWatermark


def apply_kardex_watermark_filter(
    where_parts: list[str],
    params: list[Any],
    watermark: TransactionWatermark | None,
    *,
    table_alias: str | None,
    has_fecha: bool,
    has_contador: bool,
) -> None:
    if watermark is None or not has_fecha:
        return
    prefix = f"{table_alias}." if table_alias else ""
    if has_contador and watermark.contador is not None:
        where_parts.append(
            f"({prefix}fecha > %s OR ({prefix}fecha = %s AND IFNULL({prefix}contador, 0) > %s))"
        )
        params.extend([watermark.fecha, watermark.fecha, watermark.contador])
    else:
        where_parts.append(f"{prefix}fecha > %s")
        params.append(watermark.fecha)


def build_kardex_ventas_where(
    col_cache: TableColumnCache,
    cur: Any,
    *,
    codigo: str | None,
    since_watermark: TransactionWatermark | None,
    table_alias: str | None = None,
) -> tuple[list[str], list[Any]]:
    """
    WHERE para filas kardex con venta (espejo ERP).
    table_alias: p. ej. ``k`` dentro de EXISTS sobre diariovi.
    """
    prefix = f"{table_alias}." if table_alias else ""
    where_parts = [f"IFNULL({prefix}ventas, 0) <> 0"]
    params: list[Any] = []

    if codigo:
        where_parts.append(f"TRIM({prefix}codigo) = %s")
        params.append(codigo.strip())

    kardex_cols = col_cache.columns(cur, "kardex")
    apply_kardex_watermark_filter(
        where_parts,
        params,
        since_watermark,
        table_alias=table_alias,
        has_fecha="fecha" in kardex_cols,
        has_contador="contador" in kardex_cols,
    )
    return where_parts, params


def build_sale_erp_scoped_to_kardex_exists(
    erp_table: str,
    cur: Any,
    col_cache: TableColumnCache,
    kardex_where_parts: list[str],
    kardex_params: list[Any],
) -> tuple[str, tuple[Any, ...]]:
    """
    Solo filas diariovi/ventasi que pueden enlazar alguna fila kardex del mismo alcance
    (mismo criterio de match que lookup_sale_line_in_index).
    """
    erp_cols = col_cache.columns(cur, erp_table)
    kardex_cols = col_cache.columns(cur, "kardex")
    match_parts: list[str] = []

    if "numero" in erp_cols and "numero" in kardex_cols:
        match_parts.append(
            f"(TRIM(IFNULL(k.numero,'')) <> '' "
            f"AND TRIM(k.numero) = TRIM(IFNULL(`{erp_table}`.numero,'')))"
        )
    if "contador" in erp_cols and "contador" in kardex_cols:
        match_parts.append(
            f"(k.contador IS NOT NULL AND `{erp_table}`.contador IS NOT NULL "
            f"AND k.contador = `{erp_table}`.contador)"
        )
    if "fecha" in erp_cols and "fecha" in kardex_cols:
        match_parts.append(
            f"(k.fecha IS NOT NULL AND `{erp_table}`.fecha IS NOT NULL "
            f"AND DATE(k.fecha) = DATE(`{erp_table}`.fecha))"
        )

    if not match_parts:
        return "1=0", ()

    k_where = " AND ".join(kardex_where_parts)
    exists = f"""
EXISTS (
  SELECT 1 FROM kardex k
  WHERE {k_where}
    AND TRIM(k.codigo) = TRIM(`{erp_table}`.codigo)
    AND ({' OR '.join(match_parts)})
)
""".strip()
    return exists, tuple(kardex_params)
