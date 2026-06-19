"""Filas detallepr (precios USD / % divisa) al crear o actualizar producto desde API."""

from __future__ import annotations

from typing import Any

from db.cursor_row import cursor_row_as_dict
from db.detallepr_price_from_cost import (
    fetch_detallepr_cost_row,
    recalc_detallepr_prices_from_node_cpp,
)
from db.historialp_store import log_precio_referencial_changes
from db.outbox_suppress import hub_origin_write
from db.sinv_price_from_cost import fetch_sinv_cost_price_row, recalc_prices_from_node_cpp

DETALLEPR_DIVISA_PRICE_FIELDS = ("precio1div", "precio2div", "precio3div", "precio4div")
DETALLEPR_DIVISA_PG_FIELDS = ("pg1div", "pg2div", "pg3div", "pg4div")
DETALLEPR_PRICING_COLUMNS = (
    "codigo",
    "precio1",
    "precio2",
    "precio3",
    "precio4",
    "pg1",
    "pg2",
    "pg3",
    "pg4",
)


def _to_float(value: object) -> float:
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    if type(value).__name__ == "Decimal":
        return float(value)
    try:
        return float(str(value).strip())
    except Exception:
        return 0.0


def _detallepr_row_to_divisa_fields(row: dict[str, Any]) -> dict[str, float]:
    return {
        "precio1div": _to_float(row.get("precio1")),
        "precio2div": _to_float(row.get("precio2")),
        "precio3div": _to_float(row.get("precio3")),
        "precio4div": _to_float(row.get("precio4")),
        "pg1div": _to_float(row.get("pg1")),
        "pg2div": _to_float(row.get("pg2")),
        "pg3div": _to_float(row.get("pg3")),
        "pg4div": _to_float(row.get("pg4")),
    }


def _default_divisa_fields() -> dict[str, float]:
    return {key: 0.0 for key in (*DETALLEPR_DIVISA_PRICE_FIELDS, *DETALLEPR_DIVISA_PG_FIELDS)}


def fetch_detallepr_pricing_row(cur, codigo: str) -> dict[str, float]:
    key = (codigo or "").strip()
    if not key:
        return _default_divisa_fields()
    cols = ", ".join(DETALLEPR_PRICING_COLUMNS)
    cur.execute(
        f"""
        SELECT {cols}
        FROM detallepr
        WHERE TRIM(codigo) = %s
        ORDER BY id DESC
        LIMIT 1
        """,
        (key,),
    )
    row = cursor_row_as_dict(cur.fetchone(), DETALLEPR_PRICING_COLUMNS)
    if not row:
        return _default_divisa_fields()
    return _detallepr_row_to_divisa_fields(row)


def fetch_detallepr_pricing_by_codigos(cur, codigos: list[str]) -> dict[str, dict[str, float]]:
    codes = [c.strip() for c in codigos if c and str(c).strip()]
    if not codes:
        return {}
    placeholders = ", ".join(["%s"] * len(codes))
    cols = ", ".join(DETALLEPR_PRICING_COLUMNS)
    cur.execute(
        f"""
        SELECT {cols}
        FROM detallepr d
        INNER JOIN (
          SELECT TRIM(codigo) AS codigo_key, MAX(id) AS max_id
          FROM detallepr
          WHERE TRIM(codigo) IN ({placeholders})
          GROUP BY TRIM(codigo)
        ) latest ON TRIM(d.codigo) = latest.codigo_key AND d.id = latest.max_id
        """,
        tuple(codes),
    )
    rows = cur.fetchall() or []
    out: dict[str, dict[str, float]] = {code: _default_divisa_fields() for code in codes}
    for raw in rows:
        row = cursor_row_as_dict(raw, DETALLEPR_PRICING_COLUMNS)
        if not row:
            continue
        code = str(row.get("codigo") or "").strip()
        if code in out:
            out[code] = _detallepr_row_to_divisa_fields(row)
    return out


def attach_detallepr_divisa_pricing_to_item(cur, item: dict[str, Any]) -> None:
    codigo = str(item.get("codigo") or "")
    pricing = fetch_detallepr_pricing_row(cur, codigo)
    item.update(pricing)


def attach_detallepr_divisa_pricing_to_items(cur, items: list[dict[str, Any]]) -> None:
    if not items:
        return
    by_codigo = fetch_detallepr_pricing_by_codigos(
        cur,
        [str(row.get("codigo") or "") for row in items],
    )
    for row in items:
        codigo = str(row.get("codigo") or "")
        row.update(by_codigo.get(codigo, _default_divisa_fields()))


def ensure_detallepr_for_create(cur, codigo_db: str, pg1: float) -> None:
    """Alta: fila detallepr con costos/precios en 0 y pg1 (% divisa)."""
    key = codigo_db.strip()
    if not key:
        raise ValueError("detallepr requires codigo")
    pg1_val = _to_float(pg1)
    existing = fetch_detallepr_cost_row(cur, key)
    if existing:
        with hub_origin_write(cur):
            cur.execute(
                """
                UPDATE detallepr
                SET pg1 = %s
                WHERE TRIM(codigo) = %s
                ORDER BY id DESC
                LIMIT 1
                """,
                (pg1_val, key),
            )
        return
    with hub_origin_write(cur):
        cur.execute(
            """
            INSERT INTO detallepr (
              codigo,
              precio1, precio2, precio3, precio4,
              costo, costopro, costoant, cambiodc,
              pg1, pg2, pg3, pg4
            )
            VALUES (%s, 0, 0, 0, 0, 0, 0, 0, 0, %s, 0, 0, 0)
            """,
            (key, pg1_val),
        )


def apply_inventario_pg1_pricing(cur, codigo_db: str, pg1: float) -> None:
    """
    Sincroniza pg1 en sinv (Bs + divisa) y detallepr; recalcula precio1..4
    en ambas tablas si hay costopro > 0.
    """
    key = codigo_db.strip()
    if not key:
        raise ValueError("inventario pricing requires codigo")
    pg1_val = _to_float(pg1)

    sinv_row_before = fetch_sinv_cost_price_row(cur, key)
    old_precio1_bs = (
        _to_float(sinv_row_before.get("precio1")) if sinv_row_before else 0.0
    )
    det_row_before = fetch_detallepr_cost_row(cur, key)
    old_precio1_usd = (
        _to_float(det_row_before.get("precio1")) if det_row_before else 0.0
    )

    ensure_detallepr_for_create(cur, key, pg1_val)

    with hub_origin_write(cur):
        cur.execute(
            """
            UPDATE sinv
            SET pg1 = %s,
                pg1div = %s
            WHERE TRIM(codigo) = %s
            """,
            (pg1_val, pg1_val, key),
        )

    with hub_origin_write(cur):
        cur.execute(
            """
            UPDATE detallepr
            SET pg1 = %s
            WHERE TRIM(codigo) = %s
            ORDER BY id DESC
            LIMIT 1
            """,
            (pg1_val, key),
        )

    sinv_row = fetch_sinv_cost_price_row(cur, key)
    bs_updates = recalc_prices_from_node_cpp(cur, key)
    usd_updates = recalc_detallepr_prices_from_node_cpp(cur, key, sinv_row=sinv_row)

    new_precio1_bs = (
        _to_float(bs_updates["precio1"])
        if "precio1" in bs_updates
        else old_precio1_bs
    )
    new_precio1_usd = (
        _to_float(usd_updates["precio1"])
        if "precio1" in usd_updates
        else old_precio1_usd
    )
    log_precio_referencial_changes(
        cur,
        key,
        old_precio1_bs=old_precio1_bs,
        new_precio1_bs=new_precio1_bs,
        old_precio1_usd=old_precio1_usd,
        new_precio1_usd=new_precio1_usd,
    )


def apply_inventario_create_pricing(cur, codigo_db: str, pg1: float) -> None:
    """Tras alta sinv: deja precios manuales en 0 y aplica pg1 + recálculo si hay CPP."""
    key = codigo_db.strip()
    if not key:
        raise ValueError("inventario create requires codigo")
    with hub_origin_write(cur):
        cur.execute(
            """
            UPDATE sinv
            SET precio1 = 0,
                precio1div = 0
            WHERE TRIM(codigo) = %s
            """,
            (key,),
        )
    apply_inventario_pg1_pricing(cur, key, pg1)
