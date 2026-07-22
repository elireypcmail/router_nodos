"""Enriquecimiento ERP en el worker antes de POST al router (webhooks)."""

from __future__ import annotations

from typing import Any

from db.mysql import MySqlClient
from outbox.erp_fetch import (
    fetch_detalle_lotes,
    fetch_detallepr_row,
    fetch_diariov_by_ccaja,
    fetch_diariovi_line,
    fetch_kardex_obs,
    fetch_lotes_aggregated,
    fetch_scom_line,
    fetch_sinv_row,
    fetch_sprv_row,
    parse_sale_keys,
)
from outbox.kobs_parse import (
    build_movement_timestamp,
    parse_hora_column,
    parse_kobs,
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


def _kardex_indice(row: dict[str, Any]) -> object:
    return row.get("kardex_indice") if row.get("kardex_indice") is not None else row.get("indice")


def _ensure_kobs_and_hora(enriched: dict[str, Any], mysql: MySqlClient) -> None:
    """Si el trigger no mandó kobs/hora, léelos del kardex por índice."""
    needs_kobs = not str(enriched.get("kobs") or "").strip()
    needs_hora = not str(enriched.get("hora") or "").strip()
    if not needs_kobs and not needs_hora:
        return
    obs = fetch_kardex_obs(mysql, _kardex_indice(enriched))
    if not obs:
        return
    if needs_kobs and obs.get("kobs") is not None:
        enriched["kobs"] = obs["kobs"]
    if needs_hora and obs.get("hora") is not None:
        enriched["hora"] = obs["hora"]
    if not enriched.get("fecha") and obs.get("fecha") is not None:
        enriched["fecha"] = obs["fecha"]


def _attach_kobs_enrichment(enriched: dict[str, Any], mysql: MySqlClient) -> None:
    _ensure_kobs_and_hora(enriched, mysql)
    parsed = parse_kobs(enriched.get("kobs"))
    local_time = parsed.local_time or parse_hora_column(enriched.get("hora"))

    enriched["kobs_parsed"] = {
        "provider_code": parsed.provider_code,
        "local_time": local_time.strftime("%H:%M:%S") if local_time else None,
        "local_time_raw": parsed.local_time_raw,
    }
    enriched["movement_timestamp"] = build_movement_timestamp(
        enriched.get("fecha"),
        local_time,
    )

    if parsed.provider_code:
        enriched["sprv"] = fetch_sprv_row(mysql, parsed.provider_code)
    else:
        enriched["sprv"] = None


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
    _attach_kobs_enrichment(enriched, mysql)
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
    # orderId público = diariov.nordene (ccaja de diariovi liga la preventa)
    ticket = _strip_ccaja(diariovi) or ccaja
    diariov = fetch_diariov_by_ccaja(mysql, ticket) if ticket else None
    if diariov is not None:
        enriched["diariov"] = diariov
    _attach_product_bundle(enriched, codigo, mysql)
    _attach_kobs_enrichment(enriched, mysql)
    return enriched


def _strip_ccaja(diariovi: dict[str, Any]) -> str:
    return str(diariovi.get("ccaja") or "").strip()


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
    _attach_kobs_enrichment(enriched, mysql)
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
