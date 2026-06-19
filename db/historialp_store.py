"""Auditoría de cambios de precio referencial (tabla historialp del ERP)."""

from __future__ import annotations

from datetime import datetime

from core.partner_request_context import (
    HISTORIALP_MODULO_DEFAULT,
    historialp_usuario_from_context,
)
from db.outbox_suppress import hub_origin_write
from db.product_price_formula import price_ui_round_bs, price_ui_round_usd

TIPO_PRECIO1_BS = "Precio1Bs"
TIPO_PRECIO1_R = "Precio1R"


def precio1_bs_changed(old_value: float, new_value: float) -> bool:
    return price_ui_round_bs(old_value) != price_ui_round_bs(new_value)


def precio1_usd_changed(old_value: float, new_value: float) -> bool:
    return price_ui_round_usd(old_value) != price_ui_round_usd(new_value)


def _insert_historialp_row(
    cur,
    *,
    codigo: str,
    tipoprecio: str,
    valor_anterior: float,
    modulo: str,
    usuario: str,
) -> None:
    now = datetime.now()
    with hub_origin_write(cur):
        cur.execute(
            """
            INSERT INTO historialp (
              codigo,
              tipoprecio,
              valorAnterior,
              fecha,
              hora,
              modulo,
              usuario
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                codigo.strip(),
                tipoprecio,
                float(valor_anterior),
                now.strftime("%Y-%m-%d"),
                now.strftime("%H:%M:%S"),
                modulo,
                usuario,
            ),
        )


def log_precio_referencial_changes(
    cur,
    codigo: str,
    *,
    old_precio1_bs: float,
    new_precio1_bs: float,
    old_precio1_usd: float,
    new_precio1_usd: float,
    modulo: str = HISTORIALP_MODULO_DEFAULT,
    usuario: str | None = None,
) -> None:
    """
    Registra Precio1Bs y/o Precio1R solo si el recálculo cambió el valor almacenado.
    valorAnterior = precio antes del recálculo.
    """
    key = (codigo or "").strip()
    if not key:
        return

    actor = usuario if usuario is not None else historialp_usuario_from_context()

    if precio1_bs_changed(old_precio1_bs, new_precio1_bs):
        _insert_historialp_row(
            cur,
            codigo=key,
            tipoprecio=TIPO_PRECIO1_BS,
            valor_anterior=old_precio1_bs,
            modulo=modulo,
            usuario=actor,
        )

    if precio1_usd_changed(old_precio1_usd, new_precio1_usd):
        _insert_historialp_row(
            cur,
            codigo=key,
            tipoprecio=TIPO_PRECIO1_R,
            valor_anterior=old_precio1_usd,
            modulo=modulo,
            usuario=actor,
        )
