"""CPP y precios USD en detallepr (espejo de sinv_price_from_cost para dólares)."""

from __future__ import annotations

from typing import Any

from db.outbox_suppress import hub_origin_write
from db.product_price_formula import (
    price_from_costopro_pg_and_tax,
    price_ui_round_usd,
)
from db.sinv_price_from_cost import resolve_sinv_tax_pct

DETALLEPR_PRICE_PG_PAIRS: tuple[tuple[str, str], ...] = (
    ("precio1", "pg1"),
    ("precio2", "pg2"),
    ("precio3", "pg3"),
    ("precio4", "pg4"),
)

DETALLEPR_COST_FETCH = (
    "codigo",
    "costo",
    "costopro",
    "costoant",
    "cambiodc",
    "pg1",
    "pg2",
    "pg3",
    "pg4",
    "precio1",
    "precio2",
    "precio3",
    "precio4",
)


def fetch_detallepr_cost_row(cur, codigo: str) -> dict | None:
    key = (codigo or "").strip()
    if not key:
        return None
    cols = ", ".join(DETALLEPR_COST_FETCH)
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
    return cur.fetchone()


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


def usd_cost_round(amount: float) -> float:
    return price_ui_round_usd(amount)


def price_from_costopro_and_pg(
    costopro: float,
    pg: float,
    *,
    tax_pct: float = 0,
) -> float | None:
    return price_from_costopro_pg_and_tax(
        costopro,
        pg,
        tax_pct=tax_pct,
        round_fn=price_ui_round_usd,
    )


def recalc_programmed_prices_from_row(
    row: dict[str, Any],
    *,
    costopro: float,
    tax_pct: float = 0,
) -> dict[str, float]:
    out: dict[str, float] = {}
    for precio_key, pg_key in DETALLEPR_PRICE_PG_PAIRS:
        price = price_from_costopro_and_pg(
            costopro,
            _to_float(row.get(pg_key)),
            tax_pct=tax_pct,
        )
        if price is not None:
            out[precio_key] = price
    return out


def apply_detallepr_costopro_and_prices(
    cur,
    codigo_db: str,
    row: dict[str, Any],
    *,
    costopro_nuevo: float,
    tax_pct: float | None = None,
    sinv_row: dict[str, Any] | None = None,
) -> dict[str, float]:
    """CPP USD + márgenes pg1..pg4 + precios programados (misma fórmula + IVA sinv.porvg)."""
    cpp = usd_cost_round(float(costopro_nuevo))
    if cpp <= 0:
        return {}
    iva = (
        float(tax_pct)
        if tax_pct is not None
        else resolve_sinv_tax_pct(cur, codigo_db, sinv_row)
    )
    price_row = dict(row)
    price_updates = recalc_programmed_prices_from_row(
        price_row,
        costopro=cpp,
        tax_pct=iva,
    )

    set_parts: list[str] = []
    params: list[Any] = []
    for pg_key in ("pg1", "pg2", "pg3", "pg4"):
        if pg_key in row:
            set_parts.append(f"{pg_key}=%s")
            params.append(_to_float(row.get(pg_key)))
    for key, val in price_updates.items():
        set_parts.append(f"{key}=%s")
        params.append(val)
    if not set_parts:
        return {}
    params.append(codigo_db.strip())

    with hub_origin_write(cur):
        cur.execute(
            f"""
            UPDATE detallepr
            SET {", ".join(set_parts)}
            WHERE TRIM(codigo) = %s
            ORDER BY id DESC
            LIMIT 1
            """,
            tuple(params),
        )
    return price_updates


def recalc_detallepr_prices_from_node_cpp(
    cur,
    codigo_db: str,
    *,
    sinv_row: dict[str, Any] | None = None,
) -> dict[str, float]:
    """Recalcula precio1..4 USD con costopro local de detallepr."""
    row = fetch_detallepr_cost_row(cur, codigo_db)
    if not row:
        return {}
    cpp = _to_float(row.get("costopro"))
    if cpp <= 0:
        return {}
    return apply_detallepr_costopro_and_prices(
        cur,
        codigo_db,
        row,
        costopro_nuevo=cpp,
        sinv_row=sinv_row,
    )
