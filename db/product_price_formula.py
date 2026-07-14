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


def pg_from_costopro_and_price_ex_tax(costopro: float, price_ex_tax: float) -> float | None:
    """
    Inversa del margen sobre precio de venta:
      pg = 100 - (cpp / precio_sin_iva) × 100
    """
    cpp = float(costopro)
    price = float(price_ex_tax)
    if cpp <= 0 or price <= 0 or price <= cpp:
        return None
    pg = 100.0 - (cpp / price) * 100.0
    if pg <= 0 or pg >= 100:
        return None
    return pg


def price_inc_tax_from_ex_tax(
    price_ex_tax: float,
    tax_pct: float,
    round_fn: Callable[[float], float] = price_ui_round_bs,
) -> float | None:
    """precio_con_iva = precio_sin_iva × (1 + porvg/100) cuando porvg > 0."""
    ex = float(price_ex_tax)
    if ex <= 0:
        return None
    tax = float(tax_pct)
    if tax > 0:
        return round_fn(ex * (1.0 + tax / 100.0))
    return round_fn(ex)


def price_ex_tax_from_inc_tax(
    price_inc_tax: float,
    tax_pct: float,
    round_fn: Callable[[float], float] = price_ui_round_bs,
) -> float | None:
    """Quita IVA: precio_sin_iva = precio_con_iva / (1 + porvg/100)."""
    inc = float(price_inc_tax)
    if inc <= 0:
        return None
    tax = float(tax_pct)
    if tax > 0:
        return round_fn(inc / (1.0 + tax / 100.0))
    return round_fn(inc)
