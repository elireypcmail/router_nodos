"""Comparación hub vs tienda para pull de categorías y proveedores."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from sinv_compare import _norm_num, _norm_str
from sprv_store import SPRV_BODY_FIELDS

CATEGO_FIELDS = ("ccate", "ncate", "pganancia", "pdescu")

CATEGO_FIELD_LABELS: dict[str, str] = {
    "ccate": "Código categoría",
    "ncate": "Nombre categoría",
    "pganancia": "% ganancia",
    "pdescu": "% descuento",
}

SPRV_FIELD_LABELS: dict[str, str] = {
    "cod_prv": "Código proveedor",
    "nom_prv": "Nombre",
    "rif_prv": "RIF",
    "dir1_prv": "Dirección 1",
    "dir2_prv": "Dirección 2",
    "dir3_prv": "Dirección 3",
    "tel_prv": "Teléfono",
    "email1_prv": "Email 1",
    "email2_prv": "Email 2",
    "rep_prv": "Representante",
    "especial": "Especial",
    "numcuenta": "Nº cuenta",
}

_CATEGO_NUM = frozenset({"pganancia", "pdescu"})


def normalize_catego_snapshot(row: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in CATEGO_FIELDS:
        raw = row.get(key)
        if key in _CATEGO_NUM:
            out[key] = _norm_num(raw)
        else:
            out[key] = _norm_str(raw)
    return out


def normalize_sprv_snapshot(row: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in SPRV_BODY_FIELDS:
        if key == "especial":
            out[key] = (
                "si" if _norm_str(row.get(key)).lower() == "si" else "no"
            )
        else:
            out[key] = _norm_str(row.get(key))
    return out


def catego_snapshots_equal(hub_row: dict, node_row: dict) -> bool:
    return normalize_catego_snapshot(hub_row) == normalize_catego_snapshot(node_row)


def catego_diff_fields(hub_row: dict, node_row: dict) -> list[str]:
    hub_n = normalize_catego_snapshot(hub_row)
    node_n = normalize_catego_snapshot(node_row)
    return [k for k in CATEGO_FIELDS if hub_n.get(k) != node_n.get(k)]


def sprv_snapshots_equal(hub_row: dict, node_row: dict) -> bool:
    return normalize_sprv_snapshot(hub_row) == normalize_sprv_snapshot(node_row)


def sprv_diff_fields(hub_row: dict, node_row: dict) -> list[str]:
    hub_n = normalize_sprv_snapshot(hub_row)
    node_n = normalize_sprv_snapshot(node_row)
    return [k for k in SPRV_BODY_FIELDS if hub_n.get(k) != node_n.get(k)]
