"""Enriquece compras del outbox con montos ERP desde scom (no en el trigger MySQL)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from core.config import settings
from db.mysql import MySqlClient
from db.schema_cache import TableColumnCache

_KOBS_INDICE_RE = re.compile(r"Ind:\s*(\d+)", re.IGNORECASE)


@dataclass(frozen=True)
class PurchaseScomPrepareResult:
    payload: dict[str, Any] | None
    defer: bool
    reason: str = ""


def _to_float(value: Any) -> float:
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _parse_fecha(raw: Any) -> date | None:
    if raw is None:
        return None
    if isinstance(raw, date) and not isinstance(raw, datetime):
        return raw
    text = str(raw).strip()[:10]
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _kardex_unit_cost(payload: dict[str, Any]) -> float:
    return _to_float(
        payload.get("precio")
        or payload.get("costo_actual_factura")
        or payload.get("costo")
    )


def _kardex_line_total(payload: dict[str, Any]) -> float:
    cantidad = _to_float(payload.get("cantidad"))
    costo = _kardex_unit_cost(payload)
    if cantidad and costo:
        return round(cantidad * costo, 2)
    return _to_float(payload.get("monto"))


def _parse_kobs_indice(kobs: Any) -> str | None:
    text = str(kobs or "")
    match = _KOBS_INDICE_RE.search(text)
    if not match:
        return None
    return match.group(1).strip()


def _table_has_column(
    cur: Any,
    table: str,
    column: str,
    *,
    col_cache: TableColumnCache | None = None,
) -> bool:
    if col_cache is not None:
        return col_cache.has_column(cur, table, column)
    cur.execute(f"SHOW COLUMNS FROM `{table}`")
    rows = cur.fetchall() or []
    for row in rows:
        if not isinstance(row, dict):
            continue
        field = str(row.get("Field") or "").strip().lower()
        if field == column.strip().lower():
            return True
    return False


def _fetch_scom_by_indice(
    cur: Any,
    *,
    codigo: str,
    indice: str,
    col_cache: TableColumnCache | None = None,
) -> dict[str, Any] | None:
    if not _table_has_column(cur, "scom", "indice", col_cache=col_cache):
        return None
    cur.execute(
        """
        SELECT numero, cod_prv, indice, cantidad, costo, subtotal2
        FROM scom
        WHERE codigo = %s AND indice = %s
        LIMIT 1
        """,
        (codigo, indice[:30]),
    )
    return cur.fetchone()


def _fetch_scom_by_match(
    cur: Any,
    *,
    codigo: str,
    fecha: date,
    cantidad: float,
    costo: float,
    col_cache: TableColumnCache | None = None,
) -> dict[str, Any] | None:
    has_fecha = _table_has_column(cur, "scom", "fecha", col_cache=col_cache)
    has_indice = _table_has_column(cur, "scom", "indice", col_cache=col_cache)
    if has_fecha and has_indice:
        order_by = "fecha DESC, indice DESC, numero DESC"
    elif has_fecha:
        order_by = "fecha DESC, numero DESC"
    elif has_indice:
        order_by = "indice DESC, numero DESC"
    else:
        order_by = "numero DESC"
    indice_select = "indice" if has_indice else "NULL AS indice"
    cur.execute(
        f"""
        SELECT numero, cod_prv, {indice_select}, cantidad, costo, subtotal2
        FROM scom
        WHERE codigo = %s
          AND fecha = %s
          AND ABS(IFNULL(cantidad, 0) - %s) < 0.001
          AND ABS(IFNULL(costo, 0) - %s) < 0.05
        ORDER BY {order_by}
        LIMIT 1
        """,
        (codigo, fecha, cantidad, costo),
    )
    return cur.fetchone()


def lookup_scom_purchase_line(
    mysql: MySqlClient,
    payload: dict[str, Any],
    *,
    cur: Any | None = None,
    col_cache: TableColumnCache | None = None,
) -> dict[str, Any] | None:
    codigo = str(payload.get("codigo") or "").strip()
    if not codigo:
        return None

    def _lookup(active_cur: Any) -> dict[str, Any] | None:
        indice = str(payload.get("scom_indice") or "").strip()
        if not indice:
            indice = _parse_kobs_indice(payload.get("kobs")) or ""
        if indice:
            row = _fetch_scom_by_indice(
                active_cur,
                codigo=codigo,
                indice=indice,
                col_cache=col_cache,
            )
            if row:
                return row

        fecha = _parse_fecha(payload.get("fecha"))
        if not fecha:
            return None
        cantidad = _to_float(payload.get("cantidad"))
        costo = _kardex_unit_cost(payload)
        return _fetch_scom_by_match(
            active_cur,
            codigo=codigo,
            fecha=fecha,
            cantidad=cantidad,
            costo=costo,
            col_cache=col_cache,
        )

    if cur is not None:
        return _lookup(cur)

    conn = mysql.connect()
    try:
        with conn.cursor(dictionary=True) as active_cur:
            return _lookup(active_cur)
    finally:
        conn.close()


def apply_scom_to_purchase_payload(
    payload: dict[str, Any], scom: dict[str, Any]
) -> dict[str, Any]:
    out = dict(payload)
    subtotal2 = _to_float(scom.get("subtotal2"))
    costo = _to_float(scom.get("costo"))
    numero = str(scom.get("numero") or "").strip()
    if subtotal2:
        out["monto"] = subtotal2
        out["monto_source"] = "scom.subtotal2"
    if costo:
        out["precio"] = costo
        out["costo_actual_factura"] = costo
    if numero:
        out["numdoc"] = numero
        out["numero_compra"] = numero
    indice = str(scom.get("indice") or "").strip()
    if indice:
        out["scom_indice"] = indice
    cod_prv = str(scom.get("cod_prv") or "").strip()
    if cod_prv:
        out["cod_prv"] = cod_prv
    return out


def prepare_purchase_payload_for_hub(
    payload: dict[str, Any],
    *,
    attempts: int = 0,
    mysql: MySqlClient | None = None,
    cur: Any | None = None,
    col_cache: TableColumnCache | None = None,
) -> PurchaseScomPrepareResult:
    """
    Resuelve scom antes de enviar al hub.
    - Si hay fila scom: enriquece monto/precio/numdoc.
    - Si no hay fila y attempts < max: defer (reencolar pending).
    - Si no hay fila y attempts >= max: envía con fallback kardex (monto calculado).
    """
    client = mysql or MySqlClient()
    if not client.is_configured():
        out = dict(payload)
        out.setdefault("monto", _kardex_line_total(out))
        out["monto_source"] = "kardex.fallback_no_mysql"
        return PurchaseScomPrepareResult(payload=out, defer=False)

    scom = lookup_scom_purchase_line(
        client,
        payload,
        cur=cur,
        col_cache=col_cache,
    )
    if scom and _to_float(scom.get("subtotal2")) > 0:
        enriched = apply_scom_to_purchase_payload(payload, scom)
        return PurchaseScomPrepareResult(payload=enriched, defer=False)

    max_defer = int(settings.outbox_purchase_scom_max_defer_attempts)
    if attempts < max_defer:
        codigo = str(payload.get("codigo") or "").strip()
        return PurchaseScomPrepareResult(
            payload=None,
            defer=True,
            reason=f"awaiting scom line for codigo={codigo}",
        )

    out = dict(payload)
    out["monto"] = _kardex_line_total(out)
    out["monto_source"] = "kardex.fallback_max_defer"
    return PurchaseScomPrepareResult(payload=out, defer=False)
