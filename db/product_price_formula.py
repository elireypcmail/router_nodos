"""Fórmula ERP Multishop: margen sobre precio de venta + alícuota IVA (sinv.porvg)."""

from __future__ import annotations

from typing import Callable


def price_ui_round_bs(amount: float) -> float:
    return round(amount, 2)


def price_ui_round_usd(amount: float) -> float:
    return round(amount, 6)


def price_from_costopro_pg_and_tax(
    costopro: float,
    pg: float,
    *,
    tax_pct: float = 0,
    round_fn: Callable[[float], float] = price_ui_round_bs,
) -> float | None:
    """
    precioN programado cuando pgN > 0:
      base = costopro / (1 - pgN/100)
      precio = base * (1 + porvg/100)  si porvg > 0

    pgN = 0 → precio fijado manualmente (no recalcular).
    """
    cpp = float(costopro)
    pct = float(pg)
    if cpp <= 0 or pct <= 0 or pct >= 100:
        return None
    base = cpp / (1.0 - pct / 100.0)
    tax = float(tax_pct)
    if tax > 0:
        base = base * (1.0 + tax / 100.0)
    if not (base > 0 and base < float("inf")):
        return None
    return round_fn(base)
