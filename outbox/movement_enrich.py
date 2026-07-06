"""Enriquecimiento ERP en el worker antes de POST al router (webhooks)."""

from __future__ import annotations

from typing import Any

from db.mysql import MySqlClient
from outbox.erp_fetch import (
    fetch_detalle_lotes,
    fetch_detallepr_row,
    fetch_diariovi_line,
    fetch_lotes_aggregated,
    fetch_scom_line,
    fetch_sinv_row,
    parse_sale_keys,
)
from outbox.movement_tables import resolve_entity_type


class MovementEnrichmentError(RuntimeError):
    """Fila ERP aún no disponible; el outbox debe reintentar."""


def _codigo_from_row(row: dict[str, Any] | None) -> str:
    if not row:
        return ""
    return str(row.get("codigo") or "").strip()


def _purchase_numero(row: dict[str, Any]) -> str:
    return str(row.get("numdoc") or row.get("numero") or "").strip()


def _attach_product_bundle(
    enriched: dict[str, Any],
    codigo: str,
    mysql: MySqlClient,
    *,
    include_lotes: bool = True,
) -> None:
    enriched["sinv"] = fetch_sinv_row(mysql, codigo)
    enriched["detallepr"] = fetch_detallepr_row(mysql, codigo)
    if include_lotes:
        enriched["detalle"] = fetch_detalle_lotes(mysql, codigo)
        lotes, existencia_lotes = fetch_lotes_aggregated(mysql, codigo)
        enriched["lotes"] = lotes
        enriched["existencia_lotes"] = existencia_lotes


def enrich_purchase_row(
    row: dict[str, Any] | None,
    pk: dict[str, Any] | None,
    mysql: MySqlClient,
) -> dict[str, Any]:
    if not row:
        raise MovementEnrichmentError("purchase row vacío")

    codigo = _codigo_from_row(row)
    if not codigo:
        raise MovementEnrichmentError("purchase sin codigo")

    numero = _purchase_numero(row)
    scom = fetch_scom_line(mysql, numero=numero, codigo=codigo)
    if scom is None and numero:
        raise MovementEnrichmentError(
            f"scom no encontrado numero={numero!r} codigo={codigo!r}"
        )

    enriched = dict(row)
    if scom is not None:
        enriched["scom"] = scom
    _attach_product_bundle(enriched, codigo, mysql)
    return enriched


def enrich_sale_row(
    row: dict[str, Any] | None,
    pk: dict[str, Any] | None,
    mysql: MySqlClient,
) -> dict[str, Any]:
    if not row:
        raise MovementEnrichmentError("sale row vacío")

    numero, codigo, contador, ccaja = parse_sale_keys(row, pk)
    if not codigo:
        raise MovementEnrichmentError("sale sin codigo")

    diariovi = fetch_diariovi_line(
        mysql,
        numero=numero,
        codigo=codigo,
        contador=contador,
        ccaja=ccaja,
    )
    if diariovi is None:
        raise MovementEnrichmentError(
            f"diariovi no encontrado numero={numero!r} codigo={codigo!r} contador={contador!r}"
        )

    enriched = dict(row)
    enriched["diariovi"] = diariovi
    _attach_product_bundle(enriched, codigo, mysql)
    return enriched


def enrich_kardex_adjustment_row(
    row: dict[str, Any] | None,
    mysql: MySqlClient,
) -> dict[str, Any]:
    if not row:
        raise MovementEnrichmentError("kardex row vacío")

    codigo = _codigo_from_row(row)
    if not codigo:
        raise MovementEnrichmentError("kardex sin codigo")

    enriched = dict(row)
    _attach_product_bundle(enriched, codigo, mysql)
    return enriched


def enrich_movement_row(
    table_name: str,
    row: dict[str, Any] | None,
    pk: dict[str, Any] | None,
    mysql: MySqlClient,
) -> dict[str, Any] | None:
    if row is None:
        return None
    entity = resolve_entity_type(table_name, row)
    if entity == "purchase":
        return enrich_purchase_row(row, pk, mysql)
    if entity == "sale":
        return enrich_sale_row(row, pk, mysql)
    if entity == "kardex":
        return enrich_kardex_adjustment_row(row, mysql)
    return row
