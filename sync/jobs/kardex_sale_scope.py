"""Filtros kardex (ventas) y claves de lookup hacia diariovi/ventasi."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from db.schema_cache import TableColumnCache
from sync.jobs.transaction_sync_types import TransactionWatermark

KARDEX_KEYS_FETCH_BATCH = 5000


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
    """WHERE para filas kardex con venta (espejo ERP)."""
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


@dataclass
class KardexSaleLookupKeys:
    """Claves extraídas de kardex (numero / contador)."""

    by_numero: set[tuple[str, str]] = field(default_factory=set)
    by_contador: set[tuple[str, int]] = field(default_factory=set)

    def add_row(self, row: dict[str, Any]) -> None:
        codigo = str(row.get("codigo") or "").strip()
        if not codigo:
            return
        numero = str(row.get("numero") or "").strip()
        if numero:
            self.by_numero.add((codigo, numero))
        contador_raw = row.get("contador")
        if contador_raw is not None and str(contador_raw).strip() != "":
            try:
                self.by_contador.add((codigo, int(contador_raw)))
            except (TypeError, ValueError):
                pass


def collect_kardex_sale_lookup_keys(
    cur: Any,
    col_cache: TableColumnCache,
    *,
    codigo: str | None,
    since_watermark: TransactionWatermark | None,
    on_rows_read: Callable[[int], None] | None = None,
) -> KardexSaleLookupKeys:
    """Lee kardex (ventas) y arma claves numero/contador."""
    where_parts, params = build_kardex_ventas_where(
        col_cache,
        cur,
        codigo=codigo,
        since_watermark=since_watermark,
    )
    where = " AND ".join(where_parts)
    cur.execute(
        f"""
        SELECT TRIM(codigo) AS codigo, TRIM(numero) AS numero,
               ventas, contador
        FROM kardex
        WHERE {where}
        """,
        tuple(params),
    )
    keys = KardexSaleLookupKeys()
    rows_read = 0
    while True:
        batch = cur.fetchmany(KARDEX_KEYS_FETCH_BATCH)
        if not batch:
            break
        for row in batch:
            keys.add_row(row)
        rows_read += len(batch)
        if on_rows_read is not None:
            on_rows_read(rows_read)
    return keys
