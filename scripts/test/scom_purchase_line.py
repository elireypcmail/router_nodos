"""Valores de línea scom (compra ERP) para simulate_compra."""

from __future__ import annotations

import math
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

NODO_ROOT = Path(__file__).resolve().parents[2]
os.chdir(NODO_ROOT)
if str(NODO_ROOT) not in sys.path:
    sys.path.insert(0, str(NODO_ROOT))

from db.sinv_price_from_cost import recalc_programmed_prices_from_row  # noqa: E402

if TYPE_CHECKING:
    import pymysql

DEFAULT_SCOM_FACTOR = 400.0

SINV_SCOM_FETCH = (
    "codigo",
    "costo",
    "costopro",
    "porvg",
    "pg1",
    "pg2",
    "pg3",
    "pg4",
    "pg5",
    "precio1",
    "precio2",
    "precio3",
    "precio4",
    "precio5",
    "uxb",
)


def _to_float(value: object) -> float:
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip())
    except Exception:
        return 0.0


def _round2(value: float) -> float:
    return round(value, 2)


def _round4(value: float) -> float:
    return round(value, 4)


def _round6(value: float) -> float:
    return round(value, 6)


def _resolve_cpp_nuevo(
    *,
    existencia_antes: float,
    existencia_despues: float,
    cantidad_compra: float,
    cpp_nodo: float,
    costo_actual_factura: float,
) -> float:
    """Misma fórmula que hub/servidor inventario/cpp-resolve.util.ts."""
    if existencia_antes <= 0:
        if costo_actual_factura > 0 and math.isfinite(costo_actual_factura):
            return costo_actual_factura
        if cpp_nodo > 0 and math.isfinite(cpp_nodo):
            return cpp_nodo
        return 0.0

    denom = existencia_despues
    if denom == 0:
        calculado = cpp_nodo
    else:
        calculado = (
            cpp_nodo * existencia_antes + costo_actual_factura * cantidad_compra
        ) / denom

    if calculado >= 0 and math.isfinite(calculado):
        return calculado
    if cpp_nodo > 0 and math.isfinite(cpp_nodo):
        return cpp_nodo
    if costo_actual_factura > 0 and math.isfinite(costo_actual_factura):
        return costo_actual_factura
    return 0.0


def _tax_split(subtotal2: float, porvg: float) -> tuple[float, float, float, float]:
    """exento, base1, iva1 (misma semántica que filas scom del ERP)."""
    tax = _to_float(porvg)
    total = _round2(subtotal2)
    if tax <= 0:
        return total, 0.0, 0.0, 0.0
    base1 = total
    iva1 = _round4(base1 * tax / 100.0)
    return 0.0, base1, iva1, 0.0


def _pick_pg(row: dict[str, Any], n: int) -> float | None:
    val = _to_float(row.get(f"pg{n}"))
    return val if val != 0 else None


def _pick_precio(row: dict[str, Any], n: int) -> float | None:
    val = _to_float(row.get(f"precio{n}"))
    return val if val != 0 else None


def read_sinv_scom_row(
    conn: "pymysql.connections.Connection", codigo: str
) -> dict[str, Any]:
    cols = ", ".join(SINV_SCOM_FETCH)
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT {cols} FROM sinv WHERE codigo = %s LIMIT 1",
            (codigo.strip(),),
        )
        row = cur.fetchone()
    if not row:
        raise RuntimeError(f"sinv.codigo={codigo!r} not found")
    return dict(row)


def build_scom_purchase_line(
    sinv_row: dict[str, Any],
    *,
    cantidad: float,
    costo_unitario: float,
    costo_antes: float,
    costopro_antes: float,
    existencia_antes: float,
    factor: float = DEFAULT_SCOM_FACTOR,
) -> dict[str, Any]:
    """
    Réplica campos relevantes de scom tras captura de compra en ERP:
    montos, IVA (porvg), CPP nuevo, precios actuales y recalculados (nprecio*).
    """
    qty = float(cantidad)
    unit = float(costo_unitario)
    subtotal1 = _round2(unit * qty)
    subtotal2 = subtotal1
    porvg = _to_float(sinv_row.get("porvg"))
    exento, base1, iva1, iva2 = _tax_split(subtotal2, porvg)

    existencia_despues = existencia_antes + qty
    cpp_nuevo = _resolve_cpp_nuevo(
        existencia_antes=existencia_antes,
        existencia_despues=existencia_despues,
        cantidad_compra=qty,
        cpp_nodo=float(costopro_antes),
        costo_actual_factura=unit,
    )
    nuevo_costo = unit if unit != 0 else cpp_nuevo

    nprecios = recalc_programmed_prices_from_row(
        sinv_row,
        costopro=cpp_nuevo,
    )

    fx = _to_float(factor)
    costodiv = _round6(nuevo_costo / fx) if fx > 0 and nuevo_costo > 0 else None
    nprecio1 = nprecios.get("precio1")
    precio1 = _pick_precio(sinv_row, 1)
    preciodiv_ref = nprecio1 if nprecio1 is not None else precio1
    preciodiv = (
        _round6(preciodiv_ref / fx)
        if fx > 0 and preciodiv_ref is not None and preciodiv_ref > 0
        else None
    )

    uxb = _to_float(sinv_row.get("uxb"))
    line: dict[str, Any] = {
        "porvg": porvg,
        "cantidad": qty,
        "costo": unit,
        "subtotal1": subtotal1,
        "descuento1": 0.0,
        "descuento2": 0.0,
        "subtotal2": subtotal2,
        "exento": exento,
        "iva1": iva1,
        "iva2": iva2,
        "base1": base1,
        "base2": 0.0,
        "base3": 0.0,
        "iva3": 0.0,
        "aplicaprecio": "N",
        "costoant": _round2(costo_antes) if costo_antes else None,
        "nuevocosto": _round2(nuevo_costo),
        "costopro": _round2(cpp_nuevo),
        "uxb": uxb if uxb > 0 else 1.0,
        "factor": _round4(fx) if fx > 0 else 0.0,
        "costodiv": costodiv,
        "preciodiv": preciodiv,
    }

    for n in range(1, 6):
        pg = _pick_pg(sinv_row, n)
        if pg is not None:
            line[f"pg{n}"] = pg
        precio = _pick_precio(sinv_row, n)
        if precio is not None:
            line[f"precio{n}"] = precio
        nprecio = nprecios.get(f"precio{n}")
        if nprecio is not None:
            line[f"nprecio{n}"] = nprecio

    return line
