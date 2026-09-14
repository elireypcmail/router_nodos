"""Enriquecimiento de eventos catálogo/precios/costo/existencia antes del POST al router."""

from __future__ import annotations

from typing import Any

from db.calternos_store import fetch_codigos_alternos
from db.detallepr_store import attach_detallepr_divisa_pricing_to_item
from db.general_store import attach_laboratory_to_items
from db.inventario_catalog_attach import attach_category_provider_to_items
from db.mysql import MySqlClient
from db.sinvimg_store import attach_imagen_metadata
from core.json_util import json_safe
from outbox.erp_fetch import fetch_detallepr_row, fetch_sinv_row, fetch_sprv_row
from outbox.movement_enrich import MovementEnrichmentError


def _strip(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _codigo_from(row: dict[str, Any] | None, pk: dict[str, Any] | None) -> str:
    pk = pk or {}
    return _strip((row or {}).get("codigo") or pk.get("codigo"))


def _cod_prv_from(row: dict[str, Any] | None, pk: dict[str, Any] | None) -> str:
    pk = pk or {}
    return _strip((row or {}).get("cod_prv") or pk.get("cod_prv"))


def _ccate_from(row: dict[str, Any] | None, pk: dict[str, Any] | None) -> str:
    pk = pk or {}
    return _strip((row or {}).get("ccate") or pk.get("ccate"))


def _cgeneral_from(row: dict[str, Any] | None, pk: dict[str, Any] | None) -> str:
    pk = pk or {}
    return _strip((row or {}).get("cgeneral") or pk.get("cgeneral"))


def _num(value: object) -> float:
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def fetch_catego_row(mysql: MySqlClient, ccate: str) -> dict[str, Any] | None:
    code = _strip(ccate)
    if not code:
        return None
    conn = mysql.connect()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT * FROM catego WHERE TRIM(ccate)=%s LIMIT 1",
            (code,),
        )
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def fetch_general_row(mysql: MySqlClient, cgeneral: str) -> dict[str, Any] | None:
    code = _strip(cgeneral)
    if not code:
        return None
    conn = mysql.connect()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT cgeneral, ngeneral FROM `general` WHERE TRIM(cgeneral)=%s LIMIT 1",
            (code,),
        )
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def _enrich_product(mysql: MySqlClient, codigo: str) -> dict[str, Any]:
    sinv = fetch_sinv_row(mysql, codigo)
    if not sinv:
        raise MovementEnrichmentError(f"sinv not found for codigo={codigo!r}")
    conn = mysql.connect()
    try:
        cur = conn.cursor(dictionary=True)
        item = dict(sinv)
        item["codigos_alternos"] = fetch_codigos_alternos(cur, codigo)
        attach_imagen_metadata(cur, item, include_payload=True)
        attach_detallepr_divisa_pricing_to_item(cur, item)
        attach_category_provider_to_items(cur, [item])
        attach_laboratory_to_items(cur, [item])
        return item
    finally:
        conn.close()


def _enrich_precios(mysql: MySqlClient, codigo: str) -> dict[str, Any]:
    sinv = fetch_sinv_row(mysql, codigo)
    if not sinv:
        raise MovementEnrichmentError(f"sinv not found for codigo={codigo!r}")
    detallepr = fetch_detallepr_row(mysql, codigo) or {}
    return {
        "codigo": codigo,
        "precio1": _num(sinv.get("precio1")),
        "pg1": _num(sinv.get("pg1")),
        "precio1_usd": _num(detallepr.get("precio1")),
        "pg1_usd": _num(detallepr.get("pg1")),
    }


def _enrich_costo(mysql: MySqlClient, codigo: str) -> dict[str, Any]:
    sinv = fetch_sinv_row(mysql, codigo)
    if not sinv:
        raise MovementEnrichmentError(f"sinv not found for codigo={codigo!r}")
    detallepr = fetch_detallepr_row(mysql, codigo) or {}
    return {
        "codigo": codigo,
        "costo": _num(sinv.get("costo")),
        "costopro": _num(sinv.get("costopro")),
        "costo_usd": _num(detallepr.get("costo")),
        "costopro_usd": _num(detallepr.get("costopro")),
    }


def _enrich_existencia(mysql: MySqlClient, codigo: str) -> dict[str, Any]:
    sinv = fetch_sinv_row(mysql, codigo)
    if not sinv:
        raise MovementEnrichmentError(f"sinv not found for codigo={codigo!r}")
    return {
        "codigo": codigo,
        "existencia": _num(sinv.get("existencia")),
    }


def enrich_catalog_row(
    table_name: str,
    row: dict[str, Any] | None,
    pk: dict[str, Any] | None,
    mysql: MySqlClient,
) -> dict[str, Any]:
    """Devuelve row enriquecida (snake_case nodo) para el adapter Nest."""
    if table_name == "sinv":
        codigo = _codigo_from(row, pk)
        if not codigo:
            raise MovementEnrichmentError("product event missing codigo")
        return json_safe(_enrich_product(mysql, codigo))  # type: ignore[return-value]

    if table_name == "sprv":
        cod_prv = _cod_prv_from(row, pk)
        if not cod_prv:
            raise MovementEnrichmentError("provider event missing cod_prv")
        sprv = fetch_sprv_row(mysql, cod_prv)
        if not sprv:
            raise MovementEnrichmentError(f"sprv not found for cod_prv={cod_prv!r}")
        return json_safe(sprv)  # type: ignore[return-value]

    if table_name == "catego":
        ccate = _ccate_from(row, pk)
        if not ccate:
            raise MovementEnrichmentError("category event missing ccate")
        catego = fetch_catego_row(mysql, ccate)
        if not catego:
            raise MovementEnrichmentError(f"catego not found for ccate={ccate!r}")
        return json_safe(catego)  # type: ignore[return-value]

    if table_name == "general":
        cgeneral = _cgeneral_from(row, pk)
        if not cgeneral:
            raise MovementEnrichmentError("laboratory event missing cgeneral")
        general = fetch_general_row(mysql, cgeneral)
        if not general:
            raise MovementEnrichmentError(f"general not found for cgeneral={cgeneral!r}")
        return json_safe(general)  # type: ignore[return-value]

    if table_name == "precios":
        codigo = _codigo_from(row, pk)
        if not codigo:
            raise MovementEnrichmentError("precios event missing codigo")
        return json_safe(_enrich_precios(mysql, codigo))  # type: ignore[return-value]

    if table_name == "costo":
        codigo = _codigo_from(row, pk)
        if not codigo:
            raise MovementEnrichmentError("costo event missing codigo")
        return json_safe(_enrich_costo(mysql, codigo))  # type: ignore[return-value]

    if table_name == "existencia":
        codigo = _codigo_from(row, pk)
        if not codigo:
            raise MovementEnrichmentError("existencia event missing codigo")
        return json_safe(_enrich_existencia(mysql, codigo))  # type: ignore[return-value]

    raise MovementEnrichmentError(f"unsupported catalog table={table_name!r}")
