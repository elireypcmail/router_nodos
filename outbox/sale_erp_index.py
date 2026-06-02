"""
Índice en memoria de diariovi/ventasi para export transaccional masivo de ventas.

Match kardex → línea ERP:
  (codigo, numero, cantidad) → (codigo, contador) → (codigo, numero).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from db.schema_cache import TableColumnCache

SALE_ERP_JOIN_TABLES = ("diariovi", "ventasi")
KARDEX_JOIN_FETCH_BATCH = 5000


def _to_float(value: Any) -> float:
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _qty_key(cantidad: float) -> float:
    return round(cantidad, 3)


@dataclass
class SaleErpLineIndex:
    by_contador: dict[tuple[str, int], dict[str, Any]] = field(default_factory=dict)
    by_numero_qty: dict[tuple[str, str, float], dict[str, Any]] = field(
        default_factory=dict
    )
    by_numero: dict[tuple[str, str], dict[str, Any]] = field(default_factory=dict)
    row_count: int = 0


def _index_row(
    index: SaleErpLineIndex,
    row: dict[str, Any],
    *,
    erp_table: str | None = None,
) -> None:
    codigo = str(row.get("codigo") or "").strip()
    if not codigo:
        return
    index.row_count += 1
    stored = dict(row)
    if erp_table:
        stored["_erp_table"] = erp_table

    contador_raw = stored.get("contador")
    if contador_raw is not None and str(contador_raw).strip() != "":
        try:
            contador = int(contador_raw)
            index.by_contador[(codigo, contador)] = stored
        except (TypeError, ValueError):
            pass

    numero = str(stored.get("numero") or "").strip()
    cantidad = _to_float(stored.get("cantidad"))
    if numero:
        index.by_numero[(codigo, numero)] = stored
        if cantidad > 0:
            index.by_numero_qty[(codigo, numero, _qty_key(cantidad))] = stored


def _sale_erp_select_cols(cols: set[str]) -> list[str]:
    wanted = (
        "codigo",
        "contador",
        "numero",
        "fecha",
        "cantidad",
        "costo",
        "precio1",
        "precio",
        "nprecio1",
        "subtotal2",
        "subtotal1",
        "subtotal",
        "total",
        "monto",
        "ccaja",
        "cajero",
        "indice",
    )
    return [c for c in wanted if c in cols]


def _sale_erp_order_by(cols: set[str], *, alias: str | None = None) -> str:
    prefix = f"{alias}." if alias else ""
    has_fecha = "fecha" in cols
    has_contador = "contador" in cols
    has_indice = "indice" in cols
    if has_fecha and has_contador:
        return f"{prefix}fecha ASC, {prefix}contador ASC, {prefix}numero ASC"
    if has_fecha and has_indice:
        return f"{prefix}fecha ASC, {prefix}indice ASC, {prefix}numero ASC"
    if has_fecha:
        return f"{prefix}fecha ASC, {prefix}numero ASC"
    if has_contador:
        return f"{prefix}contador ASC, {prefix}numero ASC"
    return f"{prefix}numero ASC"


def _table_usable(cur: Any, col_cache: TableColumnCache, table: str) -> bool:
    try:
        cols = col_cache.columns(cur, table)
    except Exception:
        return False
    return "codigo" in cols and "numero" in cols


def build_sale_erp_line_index(
    cur: Any,
    table: str,
    *,
    col_cache: TableColumnCache | None = None,
    codigo_filter: str | None = None,
) -> SaleErpLineIndex:
    """Lectura completa filtrada por SKU (push portal por producto)."""
    cache = col_cache or TableColumnCache()
    if not _table_usable(cur, cache, table):
        return SaleErpLineIndex()
    cols = cache.columns(cur, table)
    select_cols = _sale_erp_select_cols(cols)

    where = ""
    params: tuple[Any, ...] = ()
    if codigo_filter:
        where = " WHERE TRIM(codigo) = %s"
        params = (codigo_filter.strip(),)

    col_sql = ", ".join(f"`{c}`" for c in select_cols)
    order_by = _sale_erp_order_by(cols)
    cur.execute(
        f"""
        SELECT {col_sql}
        FROM `{table}`
        {where}
        ORDER BY {order_by}
        """,
        params,
    )

    index = SaleErpLineIndex()
    while True:
        batch = cur.fetchmany(KARDEX_JOIN_FETCH_BATCH)
        if not batch:
            break
        for row in batch:
            _index_row(index, row, erp_table=table)
    return index


def _kardex_ventas_numero_subquery(kardex_where_parts: list[str]) -> str:
    """Números de factura/ticket distintos en kardex (ventas)."""
    parts = list(kardex_where_parts) + ["TRIM(numero) <> ''"]
    k_where = " AND ".join(parts)
    return f"""
      SELECT DISTINCT TRIM(numero) AS numero
      FROM kardex
      WHERE {k_where}
    """


def _stream_join_into_index(
    cur: Any,
    index: SaleErpLineIndex,
    table: str,
    *,
    col_cache: TableColumnCache,
    kardex_where_parts: list[str],
    kardex_params: tuple[Any, ...],
    erp_codigo_filter: str | None = None,
    on_batch: Callable[[str, int], None] | None = None,
) -> int:
    cols = col_cache.columns(cur, table)
    select_cols = _sale_erp_select_cols(cols)
    col_sql = ", ".join(f"d.`{c}`" for c in select_cols)
    order_by = _sale_erp_order_by(cols, alias="d")
    subq = _kardex_ventas_numero_subquery(kardex_where_parts)
    erp_where = ""
    params: list[Any] = list(kardex_params)
    if erp_codigo_filter:
        erp_where = " WHERE TRIM(d.codigo) = %s"
        params.append(erp_codigo_filter.strip())
    cur.execute(
        f"""
        SELECT {col_sql}
        FROM `{table}` d
        INNER JOIN ({subq}) kv
          ON TRIM(d.numero) = kv.numero
        {erp_where}
        ORDER BY {order_by}
        """,
        tuple(params),
    )
    rows_loaded = 0
    while True:
        batch = cur.fetchmany(KARDEX_JOIN_FETCH_BATCH)
        if not batch:
            break
        for row in batch:
            _index_row(index, row, erp_table=table)
        rows_loaded += len(batch)
        if on_batch is not None:
            on_batch(table, rows_loaded)
    return rows_loaded


def build_merged_sale_erp_index_from_kardex_join(
    cur: Any,
    *,
    col_cache: TableColumnCache | None = None,
    kardex_where_parts: list[str],
    kardex_params: tuple[Any, ...],
    erp_codigo_filter: str | None = None,
    on_batch: Callable[[str, int], None] | None = None,
) -> SaleErpLineIndex:
    """
    JOIN kardex.numero → diariovi y ventasi (una consulta por tabla ERP).
    El match fino de línea usa codigo + cantidad/contador al volcar cada fila kardex.
    """
    cache = col_cache or TableColumnCache()
    index = SaleErpLineIndex()
    for table in SALE_ERP_JOIN_TABLES:
        if not _table_usable(cur, cache, table):
            continue
        _stream_join_into_index(
            cur,
            index,
            table,
            col_cache=cache,
            kardex_where_parts=kardex_where_parts,
            kardex_params=kardex_params,
            erp_codigo_filter=erp_codigo_filter,
            on_batch=on_batch,
        )
    return index


def lookup_sale_line_in_index(
    index: SaleErpLineIndex | None,
    payload: dict[str, Any],
) -> dict[str, Any] | None:
    if index is None:
        return None
    codigo = str(payload.get("codigo") or "").strip()
    if not codigo:
        return None

    numero = str(payload.get("numero") or payload.get("numdoc") or "").strip()
    cantidad = _to_float(payload.get("cantidad"))

    if numero and cantidad > 0:
        row = index.by_numero_qty.get((codigo, numero, _qty_key(cantidad)))
        if row:
            return row

    contador_raw = payload.get("contador")
    if contador_raw is not None and str(contador_raw).strip() != "":
        try:
            contador = int(contador_raw)
            row = index.by_contador.get((codigo, contador))
            if row:
                return row
        except (TypeError, ValueError):
            pass

    if numero:
        return index.by_numero.get((codigo, numero))
    return None


def erp_table_for_index_row(row: dict[str, Any]) -> str:
    return str(row.get("_erp_table") or "diariovi").strip() or "diariovi"
