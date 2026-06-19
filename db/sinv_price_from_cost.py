"""Recalcular precios sinv desde CPP (costopro) y % ganancia programados (pg1..pg4)."""

from __future__ import annotations

from typing import Any

from db.cursor_row import cursor_row_as_dict
from db.outbox_suppress import hub_origin_write
from db.product_price_formula import (
    price_from_costopro_pg_and_tax,
    price_ui_round_bs,
)

PRICE_PG_PAIRS: tuple[tuple[str, str], ...] = (
    ("precio1", "pg1"),
    ("precio2", "pg2"),
    ("precio3", "pg3"),
    ("precio4", "pg4"),
)

SINV_COST_PRICE_FETCH = (
    "codigo",
    "costo",
    "costopro",
    "porvg",
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


def price_ui_round(amount: float) -> float:
    return price_ui_round_bs(amount)


def price_from_costopro_and_pg(
    costopro: float,
    pg: float,
    *,
    tax_pct: float = 0,
) -> float | None:
    """precioN = costopro / (1 - pg/100) × (1 + porvg/100) cuando porvg > 0."""
    return price_from_costopro_pg_and_tax(
        costopro,
        pg,
        tax_pct=tax_pct,
        round_fn=price_ui_round_bs,
    )


def _tax_pct_from_row(row: dict[str, Any]) -> float:
    return _to_float(row.get("porvg"))


def resolve_sinv_tax_pct(
    cur,
    codigo_db: str,
    sinv_row: dict[str, Any] | None = None,
) -> float:
    """Alícuota IVA (sinv.porvg) para recálculo de precios Bs y USD."""
    if isinstance(sinv_row, dict) and sinv_row.get("porvg") is not None:
        return _tax_pct_from_row(sinv_row)
    key = str(codigo_db or "").strip()
    if not key:
        return 0.0
    cur.execute(
        "SELECT porvg FROM sinv WHERE TRIM(codigo) = %s LIMIT 1",
        (key,),
    )
    row = cur.fetchone()
    if isinstance(row, dict):
        return _tax_pct_from_row(row)
    if row is not None:
        return _to_float(row[0] if isinstance(row, (list, tuple)) else row)
    return 0.0


def fetch_sinv_cost_price_row(cur, codigo: str) -> dict[str, Any] | None:
    """Fila sinv con CPP, porvg y márgenes pg1..pg4 para recálculo de precios."""
    key = str(codigo or "").strip()
    if not key:
        return None
    cols = ", ".join(SINV_COST_PRICE_FETCH)
    cur.execute(
        f"SELECT {cols} FROM sinv WHERE TRIM(codigo) = %s LIMIT 1",
        (key,),
    )
    return cursor_row_as_dict(cur.fetchone(), SINV_COST_PRICE_FETCH)


def recalc_programmed_prices_from_row(
    row: dict[str, Any],
    *,
    costopro: float,
    tax_pct: float | None = None,
) -> dict[str, float]:
    """Recalcula precio1..4 cuando pg1..4 > 0 (margen programado vs CPP)."""
    iva = _tax_pct_from_row(row) if tax_pct is None else float(tax_pct)
    out: dict[str, float] = {}
    for precio_key, pg_key in PRICE_PG_PAIRS:
        price = price_from_costopro_and_pg(
            costopro,
            _to_float(row.get(pg_key)),
            tax_pct=iva,
        )
        if price is not None:
            out[precio_key] = price
    return out


def apply_sinv_costopro_and_prices(
    cur,
    codigo_db: str,
    row: dict[str, Any],
    *,
    costopro_nuevo: float,
) -> dict[str, float]:
    """Actualiza precio1..4 en sinv con CPP local y márgenes pg1..pg4."""
    price_updates = recalc_programmed_prices_from_row(row, costopro=costopro_nuevo)
    if not price_updates:
        return {}

    set_parts: list[str] = []
    params: list[Any] = []
    for key, val in price_updates.items():
        set_parts.append(f"{key}=%s")
        params.append(val)
    params.append(codigo_db.strip())

    with hub_origin_write(cur):
        cur.execute(
            f"UPDATE sinv SET {', '.join(set_parts)} WHERE TRIM(codigo) = %s",
            tuple(params),
        )
    return price_updates


def recalc_prices_from_node_cpp(
    cur,
    codigo_db: str,
) -> dict[str, float]:
    """Tras cambio de pg1..4: recalcula precio1..4 en sinv con costopro local."""
    row = fetch_sinv_cost_price_row(cur, codigo_db)
    if not row:
        return {}
    cpp = _to_float(row.get("costopro"))
    if cpp <= 0:
        return {}
    return apply_sinv_costopro_and_prices(
        cur,
        codigo_db,
        row,
        costopro_nuevo=cpp,
    )


def apply_sinv_cost_and_prices(
    cur,
    codigo_db: str,
    row: dict[str, Any],
    *,
    costoant: float,
    nuevo_costo: float,
    costopro_nuevo: float,
) -> dict[str, float]:
    """UPDATE sinv costos + precios programados; retorna precios recalculados."""
    price_updates = recalc_programmed_prices_from_row(row, costopro=costopro_nuevo)

    set_parts = ["costoant=%s", "costo=%s", "costopro=%s"]
    params: list[Any] = [costoant, nuevo_costo, costopro_nuevo]
    for key, val in price_updates.items():
        set_parts.append(f"{key}=%s")
        params.append(val)
    params.append(codigo_db)

    with hub_origin_write(cur):
        cur.execute(
            f"UPDATE sinv SET {', '.join(set_parts)} WHERE codigo=%s",
            tuple(params),
        )
    return price_updates
