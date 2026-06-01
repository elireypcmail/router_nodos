"""Enriquece ventas del outbox con montos ERP desde diariovi."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from db.mysql import MySqlClient


@dataclass(frozen=True)
class SaleDiarioViPrepareResult:
    payload: dict[str, Any]


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


def _get_row_value(row: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in row and row.get(key) is not None:
            return row.get(key)
    return None


def _fetch_diariovi_by_numero(
    cur: Any, *, codigo: str, numero: str
) -> dict[str, Any] | None:
    cur.execute(
        """
        SELECT *
        FROM diariovi
        WHERE codigo = %s
          AND numero = %s
        ORDER BY indice DESC
        LIMIT 1
        """,
        (codigo, numero[:30]),
    )
    return cur.fetchone()


def _fetch_diariovi_by_match(
    cur: Any,
    *,
    codigo: str,
    fecha: date,
    cantidad: float,
) -> dict[str, Any] | None:
    cur.execute(
        """
        SELECT *
        FROM diariovi
        WHERE codigo = %s
          AND fecha = %s
          AND ABS(IFNULL(cantidad, 0) - %s) < 0.001
        ORDER BY indice DESC
        LIMIT 1
        """,
        (codigo, fecha, cantidad),
    )
    return cur.fetchone()


def lookup_diariovi_sale_line(
    mysql: MySqlClient, payload: dict[str, Any]
) -> dict[str, Any] | None:
    codigo = str(payload.get("codigo") or "").strip()
    if not codigo:
        return None

    conn = mysql.connect()
    try:
        with conn.cursor(dictionary=True) as cur:
            numero = str(payload.get("numero") or payload.get("numdoc") or "").strip()
            if numero:
                row = _fetch_diariovi_by_numero(cur, codigo=codigo, numero=numero)
                if row:
                    return row

            fecha = _parse_fecha(payload.get("fecha"))
            if not fecha:
                return None
            cantidad = _to_float(payload.get("cantidad"))
            return _fetch_diariovi_by_match(
                cur,
                codigo=codigo,
                fecha=fecha,
                cantidad=cantidad,
            )
    finally:
        conn.close()


def apply_diariovi_to_sale_payload(
    payload: dict[str, Any], diariovi: dict[str, Any]
) -> dict[str, Any]:
    out = dict(payload)

    numero = str(_get_row_value(diariovi, "numero") or "").strip()
    if numero:
        out["numero"] = numero
        out["numdoc"] = numero

    precio = _to_float(_get_row_value(diariovi, "precio", "pventa", "precio1"))
    if precio:
        out["precio"] = precio

    monto = _to_float(
        _get_row_value(diariovi, "total", "subtotal2", "subtotal", "monto")
    )
    if monto:
        out["monto"] = monto
        out["monto_source"] = "diariovi"

    indice = _get_row_value(diariovi, "indice")
    if indice is not None:
        out["diariovi_indice"] = str(indice).strip()

    ccaja = str(_get_row_value(diariovi, "ccaja", "cajero") or "").strip()
    if ccaja:
        out["ccaja"] = ccaja

    return out


def prepare_sale_payload_for_hub(
    payload: dict[str, Any],
    *,
    mysql: MySqlClient | None = None,
) -> SaleDiarioViPrepareResult:
    out = dict(payload)
    out.setdefault("monto", _to_float(out.get("cantidad")) * _to_float(out.get("precio")))
    out.setdefault("monto_source", "kardex.fallback")

    client = mysql or MySqlClient()
    if not client.is_configured():
        return SaleDiarioViPrepareResult(payload=out)

    row = lookup_diariovi_sale_line(client, payload)
    if row:
        out = apply_diariovi_to_sale_payload(out, row)
    return SaleDiarioViPrepareResult(payload=out)
