"""Índice en memoria de scom para export transaccional masivo de compras."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from db.schema_cache import TableColumnCache

_KOBS_INDICE_RE = re.compile(r"Ind:\s*(\d+)", re.IGNORECASE)


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


def _costo_key(costo: float) -> float:
    return round(costo, 2)


def parse_kobs_indice(kobs: Any) -> str | None:
    text = str(kobs or "")
    match = _KOBS_INDICE_RE.search(text)
    if not match:
        return None
    return match.group(1).strip()


@dataclass
class PurchaseScomIndex:
    by_indice: dict[tuple[str, str], dict[str, Any]] = field(default_factory=dict)
    by_match: dict[tuple[str, str, float, float], dict[str, Any]] = field(
        default_factory=dict
    )
    row_count: int = 0


def _index_row(index: PurchaseScomIndex, row: dict[str, Any]) -> None:
    codigo = str(row.get("codigo") or "").strip()
    if not codigo:
        return
    index.row_count += 1

    indice = str(row.get("indice") or "").strip()
    if indice:
        index.by_indice[(codigo, indice[:30])] = row

    fecha = _parse_fecha(row.get("fecha"))
    cantidad = _to_float(row.get("cantidad"))
    costo = _to_float(row.get("costo"))
    if fecha and cantidad > 0:
        index.by_match[(codigo, fecha, _qty_key(cantidad), _costo_key(costo))] = row


def build_purchase_scom_index(
    cur: Any,
    *,
    col_cache: TableColumnCache | None = None,
    codigo_filter: str | None = None,
) -> PurchaseScomIndex:
    cache = col_cache or TableColumnCache()
    cols = cache.columns(cur, "scom")
    wanted = ("codigo", "indice", "numero", "fecha", "cantidad", "costo", "subtotal2", "cod_prv")
    select_cols = [c for c in wanted if c in cols]
    if "codigo" not in select_cols:
        return PurchaseScomIndex()

    has_fecha = "fecha" in cols
    has_indice = "indice" in cols
    if has_fecha and has_indice:
        order_by = "fecha ASC, indice ASC, numero ASC"
    elif has_fecha:
        order_by = "fecha ASC, numero ASC"
    elif has_indice:
        order_by = "indice ASC, numero ASC"
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
        FROM scom
        {where}
        ORDER BY {order_by}
        """,
        params,
    )

    index = PurchaseScomIndex()
    while True:
        batch = cur.fetchmany(5000)
        if not batch:
            break
        for row in batch:
            _index_row(index, row)
    return index


def lookup_scom_in_index(
    index: PurchaseScomIndex | None,
    payload: dict[str, Any],
) -> dict[str, Any] | None:
    if index is None:
        return None
    codigo = str(payload.get("codigo") or "").strip()
    if not codigo:
        return None

    indice = str(payload.get("scom_indice") or "").strip()
    if not indice:
        indice = parse_kobs_indice(payload.get("kobs")) or ""
    if indice:
        row = index.by_indice.get((codigo, indice[:30]))
        if row:
            return row

    fecha = _parse_fecha(payload.get("fecha"))
    if not fecha:
        return None
    cantidad = _to_float(payload.get("cantidad"))
    costo = _to_float(
        payload.get("precio")
        or payload.get("costo_actual_factura")
        or payload.get("costo")
    )
    return index.by_match.get((codigo, fecha, _qty_key(cantidad), _costo_key(costo)))
