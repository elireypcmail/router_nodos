"""Recalcular precios sinv desde CPP (costopro) y % ganancia programados (pg1..pg5)."""

from __future__ import annotations

from typing import Any

from db.outbox_suppress import hub_origin_write

PRICE_PG_PAIRS: tuple[tuple[str, str], ...] = (
    ("precio1", "pg1"),
    ("precio2", "pg2"),
    ("precio3", "pg3"),
    ("precio4", "pg4"),
    ("precio5", "pg5"),
)

SINV_COST_PRICE_FETCH = (
    "codigo",
    "costo",
    "costopro",
    "precio1",
    "precio2",
    "precio3",
    "precio4",
    "precio5",
    "pg1",
    "pg2",
    "pg3",
    "pg4",
    "pg5",
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
    return round(amount, 2)


def price_from_costopro_and_pg(costopro: float, pg: float) -> float | None:
    """
    Fórmula ERP Multishop cuando pgN > 0:
      precioN = costopro / (1 - pgN/100)

    pgN = 0 → precio fijado manualmente; no recalcular esa lista.
    """
    cpp = float(costopro)
    pct = float(pg)
    if cpp <= 0 or pct <= 0 or pct >= 100:
        return None
    out = cpp / (1.0 - pct / 100.0)
    if not (out > 0 and out < float("inf")):
        return None
    return price_ui_round(out)


def recalc_programmed_prices_from_row(
    row: dict[str, Any],
    *,
    costopro: float,
) -> dict[str, float]:
    """Devuelve solo precioN con pgN > 0 programado."""
    out: dict[str, float] = {}
    for precio_key, pg_key in PRICE_PG_PAIRS:
        price = price_from_costopro_and_pg(costopro, _to_float(row.get(pg_key)))
        if price is not None:
            out[precio_key] = price
    return out


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
