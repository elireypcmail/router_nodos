"""Filas detallepr (precios USD / % divisa) al crear o actualizar producto desde API."""

from __future__ import annotations

from db.detallepr_price_from_cost import (
    fetch_detallepr_cost_row,
    recalc_detallepr_prices_from_node_cpp,
)
from db.outbox_suppress import hub_origin_write
from db.sinv_price_from_cost import fetch_sinv_cost_price_row, recalc_prices_from_node_cpp


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
    recalc_prices_from_node_cpp(cur, key)
    recalc_detallepr_prices_from_node_cpp(cur, key, sinv_row=sinv_row)


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
