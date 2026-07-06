"""Efectos ERP tras compra: historialc/historialp, sinv/detallepr precios."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

import pymysql

from _common import today

from db.product_price_formula import (
    price_ui_round_bs,
    price_ui_round_usd,
)
from db.sinv_price_from_cost import recalc_programmed_prices_from_row


def _to_float(value: object) -> float:
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip())
    except Exception:
        return 0.0


def _usd_round(amount: float) -> float:
    return round(amount, 6)


def _cost_changed(old: float, new: float) -> bool:
    return round(old, 6) != round(new, 6)


def _price_bs_changed(old: float, new: float) -> bool:
    return price_ui_round_bs(old) != price_ui_round_bs(new)


def _price_usd_changed(old: float, new: float) -> bool:
    return price_ui_round_usd(old) != price_ui_round_usd(new)


def table_has_column(
    conn: pymysql.connections.Connection, table: str, column: str
) -> bool:
    with conn.cursor() as cur:
        cur.execute(f"SHOW COLUMNS FROM `{table}` LIKE %s", (column,))
        return cur.fetchone() is not None


def format_historial_modulo_compra(
    num_compra: str, cod_prv: str, nom_prv: str = ""
) -> str:
    prv = f"{cod_prv} {nom_prv}".strip() if nom_prv else cod_prv.strip()
    return f"Compra#: {num_compra.strip()} Proveedor: {prv}"


def format_historial_usuario_erp(operador: str) -> str:
    op = (operador or "SUPERVISOR").strip() or "SUPERVISOR"
    return f"Usuario Activo: {op}"


def _now_parts() -> tuple[date, str]:
    now = datetime.now()
    return now.date(), now.strftime("%H:%M:%S")


def insert_erp_historialc(
    cur: pymysql.cursors.Cursor,
    *,
    codigo: str,
    tipoprecio: str,
    valor_anterior: float,
    modulo: str,
    usuario: str,
    fecha: date | None = None,
) -> None:
    f, h = _now_parts()
    cur.execute(
        """
        INSERT INTO historialc (
          codigo, tipoprecio, valorAnterior, fecha, hora, modulo, usuario
        ) VALUES (%s, %s, %s, %s, %s, %s, %s)
        """,
        (
            codigo.strip()[:15],
            tipoprecio[:30],
            valor_anterior,
            fecha or f,
            h,
            modulo,
            usuario[:50],
        ),
    )


def insert_erp_historialp(
    cur: pymysql.cursors.Cursor,
    *,
    codigo: str,
    tipoprecio: str,
    valor_anterior: float,
    modulo: str,
    usuario: str,
    fecha: date | None = None,
) -> None:
    f, h = _now_parts()
    cur.execute(
        """
        INSERT INTO historialp (
          codigo, tipoprecio, valorAnterior, fecha, hora, modulo, usuario
        ) VALUES (%s, %s, %s, %s, %s, %s, %s)
        """,
        (
            codigo.strip()[:15],
            tipoprecio[:30],
            valor_anterior,
            fecha or f,
            h,
            modulo,
            usuario[:50],
        ),
    )


def read_sinv_pricing_row(
    conn: pymysql.connections.Connection, codigo: str
) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT codigo, costo, costopro, costoant, precio1, precio2, precio3, precio4,
                   pg1, pg2, pg3, pg4, porvg, costodolar
            FROM sinv
            WHERE codigo = %s
            LIMIT 1
            """,
            (codigo.strip(),),
        )
        row = cur.fetchone()
    if not row:
        raise RuntimeError(f"sinv.codigo={codigo!r} not found")
    return dict(row)


def read_detallepr_row(
    conn: pymysql.connections.Connection, codigo: str
) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT codigo, costo, costopro, costoant, cambiodc,
                   pg1, pg2, pg3, pg4, precio1, precio2, precio3, precio4
            FROM detallepr
            WHERE TRIM(codigo) = %s
            ORDER BY id DESC
            LIMIT 1
            """,
            (codigo.strip(),),
        )
        row = cur.fetchone()
    return dict(row) if row else None


def bs_to_usd(amount_bs: float, factor: float) -> float | None:
    """Convierte monto Bs a USD: precio_bs / factor (tipo de cambio factura)."""
    f = _to_float(factor)
    bs = _to_float(amount_bs)
    if f <= 0 or bs <= 0:
        return None
    return _usd_round(bs / f)


def _resolve_cpp_usd(
    cpp_bs: float,
    *,
    factor: float,
    sinv_row: dict[str, Any],
    det_row: dict[str, Any] | None,
) -> float:
    converted = bs_to_usd(cpp_bs, factor)
    if converted is not None:
        return converted

    det = det_row or {}
    cambiodc = _to_float(det.get("cambiodc"))
    if cambiodc > 0:
        return _usd_round(cpp_bs / cambiodc)
    cpp_usd_local = _to_float(det.get("costopro"))
    cpp_bs_local = _to_float(sinv_row.get("costopro"))
    if cpp_bs_local > 0 and cpp_usd_local > 0:
        return _usd_round(cpp_bs * (cpp_usd_local / cpp_bs_local))
    costodolar = _to_float(sinv_row.get("costodolar"))
    if costodolar > 0:
        return _usd_round(cpp_bs / costodolar)
    return 0.0


def _ensure_detallepr_row(
    cur: pymysql.cursors.Cursor,
    codigo: str,
    *,
    cambiodc: float = 0.0,
    pg1: float = 0.0,
) -> dict[str, Any]:
    key = codigo.strip()
    cur.execute(
        """
        SELECT codigo, costo, costopro, costoant, cambiodc,
               pg1, pg2, pg3, pg4, precio1, precio2, precio3, precio4
        FROM detallepr
        WHERE TRIM(codigo) = %s
        ORDER BY id DESC
        LIMIT 1
        """,
        (key,),
    )
    row = cur.fetchone()
    if row:
        return dict(row)
    cur.execute(
        """
        INSERT INTO detallepr (
          codigo, cambiodc, costo, costopro, costoant, pg1,
          precio1, precio2, precio3, precio4, pg2, pg3, pg4
        ) VALUES (%s, %s, 0, 0, 0, %s, 0, 0, 0, 0, 0, 0, 0)
        """,
        (key, _usd_round(cambiodc), pg1),
    )
    cur.execute(
        """
        SELECT codigo, costo, costopro, costoant, cambiodc,
               pg1, pg2, pg3, pg4, precio1, precio2, precio3, precio4
        FROM detallepr
        WHERE TRIM(codigo) = %s
        ORDER BY id DESC
        LIMIT 1
        """,
        (key,),
    )
    row = cur.fetchone() or {}
    return dict(row)


def _recalc_detallepr_prices_from_bs(
    sinv_prices: dict[str, float], *, factor: float
) -> dict[str, float]:
    """Precio USD = precio Bs / factor (paridad ERP en simulación)."""
    out: dict[str, float] = {}
    for key, val_bs in sinv_prices.items():
        usd = bs_to_usd(val_bs, factor)
        if usd is not None:
            out[key] = usd
    return out


def apply_erp_post_compra_effects(
    conn: pymysql.connections.Connection,
    *,
    codigo: str,
    costo_antes: float,
    costopro_antes: float,
    costo_nuevo: float,
    costopro_nuevo: float,
    num_compra: str,
    cod_prv: str,
    nom_prv: str = "",
    factor: float | None = None,
    operador: str = "SUPERVISOR",
    recalc_precios: bool = True,
    fecha: date | None = None,
) -> dict[str, Any]:
    """
    Réplica ERP post-compra:
    - historialc: Costo Actual, Costo Promedio, Costo Referencial
    - sinv precios programados desde CPP
    - detallepr costo/costopro/precios USD
    - historialp: Precio1Bs, Precio1, Precio1R
    """
    sinv_before = read_sinv_pricing_row(conn, codigo)
    det_before = read_detallepr_row(conn, codigo)
    old_precio1_bs = _to_float(sinv_before.get("precio1"))
    old_precio1_usd = _to_float((det_before or {}).get("precio1"))
    old_costo_ref = _to_float((det_before or {}).get("costo"))

    modulo_compra = format_historial_modulo_compra(num_compra, cod_prv, nom_prv)
    usuario = format_historial_usuario_erp(operador)
    fecha_val = fecha or today()
    summary: dict[str, Any] = {
        "historialc": [],
        "historialp": [],
        "sinv_precios": {},
        "detallepr": {},
    }

    with conn.cursor() as cur:
        if _cost_changed(costo_antes, costo_nuevo):
            insert_erp_historialc(
                cur,
                codigo=codigo,
                tipoprecio="Costo Actual",
                valor_anterior=round(costo_antes, 6),
                modulo=modulo_compra,
                usuario=usuario,
                fecha=fecha_val,
            )
            summary["historialc"].append("Costo Actual")

        if _cost_changed(costopro_antes, costopro_nuevo):
            insert_erp_historialc(
                cur,
                codigo=codigo,
                tipoprecio="Costo Promedio",
                valor_anterior=round(costopro_antes, 6),
                modulo=modulo_compra,
                usuario=usuario,
                fecha=fecha_val,
            )
            summary["historialc"].append("Costo Promedio")

        if not recalc_precios or costopro_nuevo <= 0:
            return summary

        sinv_prices = recalc_programmed_prices_from_row(
            sinv_before,
            costopro=costopro_nuevo,
        )
        if sinv_prices:
            set_parts = []
            params: list[Any] = []
            for key, val in sinv_prices.items():
                set_parts.append(f"{key}=%s")
                params.append(val)
            params.append(codigo.strip())
            cur.execute(
                f"UPDATE sinv SET {', '.join(set_parts)} WHERE codigo=%s",
                tuple(params),
            )
            summary["sinv_precios"] = sinv_prices

        cambiodc = _to_float(factor) if factor and factor > 0 else 0.0
        if cambiodc <= 0:
            cambiodc = _to_float((det_before or {}).get("cambiodc"))
        if cambiodc <= 0:
            cambiodc = _to_float(sinv_before.get("costodolar"))

        det_row = _ensure_detallepr_row(
            cur,
            codigo,
            cambiodc=cambiodc,
            pg1=_to_float(sinv_before.get("pg1")),
        )
        cpp_usd = _resolve_cpp_usd(
            costopro_nuevo,
            factor=cambiodc,
            sinv_row=sinv_before,
            det_row=det_row,
        )
        costo_usd_nuevo = bs_to_usd(costo_nuevo, cambiodc)
        if costo_usd_nuevo is None:
            costo_usd_nuevo = _to_float(det_row.get("costo"))
        costoant_usd = (
            bs_to_usd(costo_antes, cambiodc)
            if bs_to_usd(costo_antes, cambiodc) is not None
            else (old_costo_ref if old_costo_ref > 0 else costo_usd_nuevo)
        )

        det_prices = (
            _recalc_detallepr_prices_from_bs(sinv_prices, factor=cambiodc)
            if cambiodc > 0 and sinv_prices
            else {}
        )

        set_parts = ["costo=%s", "costoant=%s", "costopro=%s"]
        params = [costo_usd_nuevo, costoant_usd, cpp_usd if cpp_usd > 0 else _to_float(det_row.get("costopro"))]
        for key, val in det_prices.items():
            set_parts.append(f"{key}=%s")
            params.append(val)
        params.append(codigo.strip())
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
        summary["detallepr"] = {
            "costo": costo_usd_nuevo,
            "costopro": cpp_usd,
            **det_prices,
        }

        if _cost_changed(old_costo_ref, costo_usd_nuevo):
            insert_erp_historialc(
                cur,
                codigo=codigo,
                tipoprecio="Costo Referencial",
                valor_anterior=_usd_round(old_costo_ref),
                modulo="Precios Ficha INV",
                usuario=usuario,
                fecha=fecha_val,
            )
            summary["historialc"].append("Costo Referencial")

        new_precio1_bs = _to_float(sinv_prices.get("precio1", old_precio1_bs))
        new_precio1_usd = _to_float(det_prices.get("precio1", old_precio1_usd))

        if _price_bs_changed(old_precio1_bs, new_precio1_bs):
            valor = price_ui_round_bs(old_precio1_bs)
            insert_erp_historialp(
                cur,
                codigo=codigo,
                tipoprecio="Precio1Bs",
                valor_anterior=valor,
                modulo="Precios Referenciales",
                usuario=usuario,
                fecha=fecha_val,
            )
            insert_erp_historialp(
                cur,
                codigo=codigo,
                tipoprecio="Precio1",
                valor_anterior=valor,
                modulo="Precios Ficha INV",
                usuario=usuario,
                fecha=fecha_val,
            )
            summary["historialp"].extend(["Precio1Bs", "Precio1"])

        if _price_usd_changed(old_precio1_usd, new_precio1_usd):
            insert_erp_historialp(
                cur,
                codigo=codigo,
                tipoprecio="Precio1R",
                valor_anterior=price_ui_round_usd(old_precio1_usd),
                modulo="Precios Referenciales",
                usuario=usuario,
                fecha=fecha_val,
            )
            summary["historialp"].append("Precio1R")

    return summary
