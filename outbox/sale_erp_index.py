"""
Índice en memoria de ventasi/diariovi para export transaccional masivo.

Match kardex → línea ERP (mismo criterio que backup-FF23834):
  codigo (SKU) + numero (factura) + cantidad; luego contador; luego fecha+cantidad.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from db.schema_cache import TableColumnCache


def _to_float(value: Any) -> float:
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _parse_fecha(raw: Any) -> str | None:
    if raw is None:
        return None
    if isinstance(raw, date) and not isinstance(raw, datetime):
        return raw.isoformat()
    text = str(raw).strip()[:10]
    return text if text and text != "0000-00-00" else None


def _qty_key(cantidad: float) -> float:
    return round(cantidad, 3)


@dataclass
class SaleErpLineIndex:
    by_contador: dict[tuple[str, int], dict[str, Any]] = field(default_factory=dict)
    by_numero_qty: dict[tuple[str, str, float], dict[str, Any]] = field(
        default_factory=dict
    )
    by_numero: dict[tuple[str, str], dict[str, Any]] = field(default_factory=dict)
    by_fecha_qty: dict[tuple[str, str, float], dict[str, Any]] = field(
        default_factory=dict
    )
    row_count: int = 0


def _index_row(index: SaleErpLineIndex, row: dict[str, Any]) -> None:
    codigo = str(row.get("codigo") or "").strip()
    if not codigo:
        return
    index.row_count += 1

    contador_raw = row.get("contador")
    if contador_raw is not None and str(contador_raw).strip() != "":
        try:
            contador = int(contador_raw)
            index.by_contador[(codigo, contador)] = row
        except (TypeError, ValueError):
            pass

    numero = str(row.get("numero") or "").strip()
    cantidad = _to_float(row.get("cantidad"))
    if numero:
        index.by_numero[(codigo, numero)] = row
        if cantidad > 0:
            index.by_numero_qty[(codigo, numero, _qty_key(cantidad))] = row

    fecha = _parse_fecha(row.get("fecha"))
    if fecha and cantidad > 0:
        index.by_fecha_qty[(codigo, fecha, _qty_key(cantidad))] = row


def build_sale_erp_line_index(
    cur: Any,
    table: str,
    *,
    col_cache: TableColumnCache | None = None,
    codigo_filter: str | None = None,
) -> SaleErpLineIndex:
    """
    Una sola lectura de ventasi/diariovi; claves más recientes ganan (ORDER BY fecha, contador ASC).
    """
    cache = col_cache or TableColumnCache()
    cols = cache.columns(cur, table)
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
    select_cols = [c for c in wanted if c in cols]
    if "codigo" not in select_cols:
        return SaleErpLineIndex()

    has_fecha = "fecha" in cols
    has_contador = "contador" in cols
    has_indice = "indice" in cols

    if has_fecha and has_contador:
        order_by = "fecha ASC, contador ASC, numero ASC"
    elif has_fecha and has_indice:
        order_by = "fecha ASC, indice ASC, numero ASC"
    elif has_fecha:
        order_by = "fecha ASC, numero ASC"
    elif has_contador:
        order_by = "contador ASC, numero ASC"
    else:
        order_by = "numero ASC"

    where = ""
    params: tuple[Any, ...] = ()
    if codigo_filter:
        where = " WHERE TRIM(codigo) = %s"
        params = (codigo_filter.strip(),)

    col_sql = ", ".join(f"`{c}`" for c in select_cols)
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
        batch = cur.fetchmany(5000)
        if not batch:
            break
        for row in batch:
            _index_row(index, row)
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
        row = index.by_numero.get((codigo, numero))
        if row:
            return row

    fecha = _parse_fecha(payload.get("fecha"))
    if fecha and cantidad > 0:
        return index.by_fecha_qty.get((codigo, fecha, _qty_key(cantidad)))
    return None
