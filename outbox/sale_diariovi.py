"""
Enriquece ventas con línea ERP sellada.

- **ventasi**: nombre lógico del outbox (trigger kardex).
- **diariovi**: misma forma de línea; en muchas tiendas es donde están precio/subtotal2
  (ver backup-FF23834: kardex.codigo + kardex.numero + kardex.ventas ↔ diariovi).

Match (orden): (codigo, numero, cantidad) → (codigo, contador) → (codigo, numero) → fecha+cantidad.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from db.mysql import MySqlClient
from db.schema_cache import TableColumnCache
from outbox.sale_erp_index import SaleErpLineIndex, lookup_sale_line_in_index
from outbox.sale_erp_line import (
    _to_float,
    apply_erp_sale_line_to_payload,
    erp_sale_line_has_pricing,
    lookup_sale_line_in_table,
)
from outbox.sale_ventasi import lookup_ventasi_sale_line


@dataclass(frozen=True)
class SaleDiarioViPrepareResult:
    payload: dict[str, Any]


def lookup_diariovi_sale_line(
    mysql: MySqlClient,
    payload: dict[str, Any],
    *,
    cur: Any | None = None,
    col_cache: TableColumnCache | None = None,
) -> dict[str, Any] | None:
    return lookup_sale_line_in_table(
        mysql,
        payload,
        table="diariovi",
        cur=cur,
        col_cache=col_cache,
    )


def apply_diariovi_to_sale_payload(
    payload: dict[str, Any], diariovi: dict[str, Any]
) -> dict[str, Any]:
    """Compatibilidad: mismo contrato que apply_erp_sale_line_to_payload."""
    return apply_erp_sale_line_to_payload(payload, diariovi, source="diariovi")


def _resolve_sale_erp_line(
    payload: dict[str, Any],
    *,
    mysql: MySqlClient,
    cur: Any | None,
    col_cache: TableColumnCache | None,
    ventasi_index: SaleErpLineIndex | None,
    diariovi_index: SaleErpLineIndex | None,
) -> tuple[dict[str, Any] | None, str]:
    """diariovi primero (suele tener las líneas); luego ventasi."""
    sources: list[tuple[str, SaleErpLineIndex | None, Callable[..., dict | None]]] = [
        ("diariovi", diariovi_index, lookup_diariovi_sale_line),
        ("ventasi", ventasi_index, lookup_ventasi_sale_line),
    ]
    for source, index, lookup_sql in sources:
        if index is not None:
            row = lookup_sale_line_in_index(index, payload)
        else:
            row = lookup_sql(mysql, payload, cur=cur, col_cache=col_cache)
        if row and erp_sale_line_has_pricing(row):
            return row, source
    return None, ""


def prepare_sale_payload_for_hub(
    payload: dict[str, Any],
    *,
    mysql: MySqlClient | None = None,
    cur: Any | None = None,
    col_cache: TableColumnCache | None = None,
    ventasi_index: SaleErpLineIndex | None = None,
    diariovi_index: SaleErpLineIndex | None = None,
) -> SaleDiarioViPrepareResult:
    out = dict(payload)
    cantidad = _to_float(out.get("cantidad"))
    precio_k = _to_float(out.get("precio"))
    if cantidad and precio_k:
        out.setdefault("monto", round(cantidad * precio_k, 2))
    else:
        out.setdefault("monto", 0.0)
    out.setdefault("monto_source", "kardex.fallback")

    client = mysql or MySqlClient()
    if not client.is_configured():
        return SaleDiarioViPrepareResult(payload=out)

    row, source = _resolve_sale_erp_line(
        payload,
        mysql=client,
        cur=cur,
        col_cache=col_cache,
        ventasi_index=ventasi_index,
        diariovi_index=diariovi_index,
    )
    if row and source:
        enriched = apply_erp_sale_line_to_payload(out, row, source=source)
        return SaleDiarioViPrepareResult(payload=enriched)

    return SaleDiarioViPrepareResult(payload=out)
