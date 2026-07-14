"""Aplicar precio sin IVA USD → margen (pg) y precio con IVA en sinv/detallepr."""

from __future__ import annotations

from typing import Any, Literal

from db.detallepr_price_from_cost import fetch_detallepr_cost_row
from db.detallepr_store import ensure_detallepr_for_create
from db.historialp_store import log_precio_referencial_changes
from db.outbox_suppress import hub_origin_write
from db.product_porvg import validate_porvg
from db.product_price_formula import (
    pg_from_costopro_and_price_ex_tax,
    price_ex_tax_from_inc_tax,
    price_inc_tax_from_ex_tax,
    price_ui_round_bs,
    price_ui_round_usd,
)
from db.sinv_price_from_cost import fetch_sinv_cost_price_row

PriceFromNetMode = Literal["solo_impuesto", "solo_precio", "completo"]


class PriceFromNetError(Exception):
    """Error de validación o negocio al aplicar precio desde neto."""

    def __init__(self, message: str, *, status_code: int = 422) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


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


def _fetch_sinv_pricing_row(cur, codigo: str) -> dict[str, Any] | None:
    key = (codigo or "").strip()
    if not key:
        return None
    cur.execute(
        """
        SELECT costopro, porvg, precio1, precio1div, pg1, pg1div
        FROM sinv
        WHERE TRIM(codigo) = %s
        LIMIT 1
        """,
        (key,),
    )
    row = cur.fetchone()
    if not row:
        return None
    if isinstance(row, dict):
        return row
    return {
        "costopro": row[0],
        "porvg": row[1],
        "precio1": row[2],
        "precio1div": row[3],
        "pg1": row[4],
        "pg1div": row[5],
    }


def _resolve_mode(
    *,
    price_ex_tax_usd: float | None,
    porvg_request: float | None,
) -> PriceFromNetMode:
    has_price = price_ex_tax_usd is not None
    has_tax = porvg_request is not None
    if not has_price and not has_tax:
        raise PriceFromNetError(
            "precio_sin_iva_usd or porvg is required",
        )
    if has_price and has_tax:
        return "completo"
    if has_price:
        return "solo_precio"
    return "solo_impuesto"


def _validate_cpp_vs_price(
    *,
    price_ex_tax_usd: float,
    price_ex_tax_bs: float,
    cpp_usd: float,
    cpp_bs: float,
) -> None:
    if cpp_usd <= 0 or cpp_bs <= 0:
        raise PriceFromNetError("local cpp must be greater than zero")
    if price_ex_tax_usd <= cpp_usd:
        raise PriceFromNetError(
            "priceExTaxUsd must be greater than local cpp (USD lane)",
        )
    if price_ex_tax_bs <= cpp_bs:
        raise PriceFromNetError(
            "priceExTaxUsd × exchangeRate must be greater than local cpp (Bs lane)",
        )


def _build_response_payload(
    *,
    modo: PriceFromNetMode,
    cpp_bs: float,
    cpp_usd: float,
    psi_bs: float,
    psi_usd: float,
    pci_bs: float,
    pci_usd: float,
    pg_bs: float,
    pg_usd: float,
    porvg: float,
) -> dict[str, Any]:
    return {
        "cpp_bs": cpp_bs,
        "cpp_usd": cpp_usd,
        "precio_sin_iva_bs": psi_bs,
        "precio_sin_iva_usd": psi_usd,
        "precio_con_iva_bs": pci_bs,
        "precio_con_iva_usd": pci_usd,
        "pg_bs": pg_bs,
        "pg_usd": pg_usd,
        "porvg": porvg,
        "modo": modo,
    }


def apply_price_from_net(
    cur,
    codigo: str,
    *,
    price_ex_tax_usd: float | None = None,
    exchange_rate: float | None = None,
    porvg: float | None = None,
) -> dict[str, Any]:
    key = (codigo or "").strip()
    if not key:
        raise PriceFromNetError("codigo is required")

    sinv_row = _fetch_sinv_pricing_row(cur, key)
    if not sinv_row:
        raise PriceFromNetError("product not found", status_code=404)

    det_row = fetch_detallepr_cost_row(cur, key)

    cpp_bs = _to_float(sinv_row.get("costopro"))
    cpp_usd = _to_float(det_row.get("costopro")) if det_row else 0.0
    porvg_actual = _to_float(sinv_row.get("porvg"))

    old_precio1_bs = _to_float(sinv_row.get("precio1"))
    old_precio1_usd = (
        _to_float(det_row.get("precio1"))
        if det_row
        else _to_float(sinv_row.get("precio1div"))
    )
    pg_bs_existing = _to_float(sinv_row.get("pg1"))
    pg_usd_existing = (
        _to_float(det_row.get("pg1"))
        if det_row
        else _to_float(sinv_row.get("pg1div"))
    )

    porvg_request = validate_porvg(porvg) if porvg is not None else None
    mode = _resolve_mode(
        price_ex_tax_usd=price_ex_tax_usd,
        porvg_request=porvg_request,
    )

    if mode in ("solo_precio", "completo"):
        if exchange_rate is None or float(exchange_rate) <= 0:
            raise PriceFromNetError(
                "tasa (exchangeRate) is required and must be > 0 when precio_sin_iva_usd is sent",
            )
        psi_usd = price_ui_round_usd(float(price_ex_tax_usd))
        psi_bs = price_ui_round_bs(float(price_ex_tax_usd) * float(exchange_rate))
        _validate_cpp_vs_price(
            price_ex_tax_usd=psi_usd,
            price_ex_tax_bs=psi_bs,
            cpp_usd=cpp_usd,
            cpp_bs=cpp_bs,
        )
        pg_usd_val = pg_from_costopro_and_price_ex_tax(cpp_usd, psi_usd)
        pg_bs_val = pg_from_costopro_and_price_ex_tax(cpp_bs, psi_bs)
        if pg_usd_val is None or pg_bs_val is None:
            raise PriceFromNetError("could not derive markup percent from price and cpp")

        tax_pct = float(porvg_request) if mode == "completo" else porvg_actual
        pci_usd = price_inc_tax_from_ex_tax(
            psi_usd, tax_pct, round_fn=price_ui_round_usd
        )
        pci_bs = price_inc_tax_from_ex_tax(
            psi_bs, tax_pct, round_fn=price_ui_round_bs
        )
        if pci_usd is None or pci_bs is None:
            raise PriceFromNetError("could not derive price with tax")

        ensure_detallepr_for_create(cur, key, pg_usd_val)

        set_sinv = [
            "pg1 = %s",
            "pg1div = %s",
            "precio1 = %s",
            "precio1div = %s",
        ]
        params_sinv: list[Any] = [pg_bs_val, pg_usd_val, pci_bs, pci_usd]
        if mode == "completo":
            set_sinv.append("porvg = %s")
            params_sinv.append(tax_pct)
        params_sinv.append(key)

        with hub_origin_write(cur):
            cur.execute(
                f"""
                UPDATE sinv
                SET {", ".join(set_sinv)}
                WHERE TRIM(codigo) = %s
                """,
                tuple(params_sinv),
            )

        with hub_origin_write(cur):
            cur.execute(
                """
                UPDATE detallepr
                SET pg1 = %s, precio1 = %s
                WHERE TRIM(codigo) = %s
                ORDER BY id DESC
                LIMIT 1
                """,
                (pg_usd_val, pci_usd, key),
            )

        log_precio_referencial_changes(
            cur,
            key,
            old_precio1_bs=old_precio1_bs,
            new_precio1_bs=pci_bs,
            old_precio1_usd=old_precio1_usd,
            new_precio1_usd=pci_usd,
        )

        return _build_response_payload(
            modo=mode,
            cpp_bs=cpp_bs,
            cpp_usd=cpp_usd,
            psi_bs=psi_bs,
            psi_usd=psi_usd,
            pci_bs=pci_bs,
            pci_usd=pci_usd,
            pg_bs=pg_bs_val,
            pg_usd=pg_usd_val,
            porvg=tax_pct,
        )

    # solo_impuesto
    new_tax = float(porvg_request)
    if old_precio1_bs <= 0 or old_precio1_usd <= 0:
        raise PriceFromNetError(
            "precio1 must be greater than zero to recalculate tax only",
        )

    psi_bs = price_ex_tax_from_inc_tax(
        old_precio1_bs,
        porvg_actual,
        round_fn=price_ui_round_bs,
    )
    psi_usd = price_ex_tax_from_inc_tax(
        old_precio1_usd,
        porvg_actual,
        round_fn=price_ui_round_usd,
    )
    if psi_bs is None or psi_usd is None:
        raise PriceFromNetError("could not derive price ex tax from current precio1")

    pci_bs = price_inc_tax_from_ex_tax(
        psi_bs, new_tax, round_fn=price_ui_round_bs
    )
    pci_usd = price_inc_tax_from_ex_tax(
        psi_usd, new_tax, round_fn=price_ui_round_usd
    )
    if pci_bs is None or pci_usd is None:
        raise PriceFromNetError("could not derive price with tax")

    if not det_row:
        ensure_detallepr_for_create(cur, key, pg_usd_existing)

    with hub_origin_write(cur):
        cur.execute(
            """
            UPDATE sinv
            SET porvg = %s, precio1 = %s, precio1div = %s
            WHERE TRIM(codigo) = %s
            """,
            (new_tax, pci_bs, pci_usd, key),
        )

    with hub_origin_write(cur):
        cur.execute(
            """
            UPDATE detallepr
            SET precio1 = %s
            WHERE TRIM(codigo) = %s
            ORDER BY id DESC
            LIMIT 1
            """,
            (pci_usd, key),
        )

    log_precio_referencial_changes(
        cur,
        key,
        old_precio1_bs=old_precio1_bs,
        new_precio1_bs=pci_bs,
        old_precio1_usd=old_precio1_usd,
        new_precio1_usd=pci_usd,
    )

    return _build_response_payload(
        modo=mode,
        cpp_bs=cpp_bs,
        cpp_usd=cpp_usd,
        psi_bs=psi_bs,
        psi_usd=psi_usd,
        pci_bs=pci_bs,
        pci_usd=pci_usd,
        pg_bs=pg_bs_existing,
        pg_usd=pg_usd_existing,
        porvg=new_tax,
    )
