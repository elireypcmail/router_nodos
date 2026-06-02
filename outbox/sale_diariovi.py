"""Enriquece ventas: ventasi (línea sellada ERP) y fallback diariovi."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from db.mysql import MySqlClient
from db.schema_cache import TableColumnCache
from outbox.sale_erp_line import (
    _to_float,
    apply_erp_sale_line_to_payload,
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


def prepare_sale_payload_for_hub(
    payload: dict[str, Any],
    *,
    mysql: MySqlClient | None = None,
    cur: Any | None = None,
    col_cache: TableColumnCache | None = None,
) -> SaleDiarioViPrepareResult:
    """
    Resuelve ventasi (precio1 + subtotal2 sellado) antes de enviar al hub.
    Si no hay fila en ventasi, intenta diariovi; si no, fallback kardex.
    """
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

    ventasi = lookup_ventasi_sale_line(
        client,
        payload,
        cur=cur,
        col_cache=col_cache,
    )
    if ventasi:
        subtotal_v = _to_float(ventasi.get("subtotal2"))
        precio_v = _to_float(
            ventasi.get("precio1") or ventasi.get("precio") or ventasi.get("nprecio1")
        )
        if subtotal_v > 0 or precio_v > 0:
            enriched = apply_erp_sale_line_to_payload(out, ventasi, source="ventasi")
            return SaleDiarioViPrepareResult(payload=enriched)

    diariovi = lookup_diariovi_sale_line(
        client,
        payload,
        cur=cur,
        col_cache=col_cache,
    )
    if diariovi:
        monto_line = _to_float(
            diariovi.get("subtotal2")
            or diariovi.get("total")
            or diariovi.get("subtotal")
            or diariovi.get("monto")
        )
        precio_line = _to_float(
            diariovi.get("precio1") or diariovi.get("precio") or diariovi.get("pventa")
        )
        if monto_line > 0 or precio_line > 0:
            enriched = apply_erp_sale_line_to_payload(out, diariovi, source="diariovi")
            return SaleDiarioViPrepareResult(payload=enriched)

    return SaleDiarioViPrepareResult(payload=out)
