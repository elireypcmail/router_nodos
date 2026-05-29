"""Comparación de maestros sinv (hub vs tienda) para pull inicial."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from sinv_store import SINV_HUB_FIELDS

SINV_FIELD_LABELS: dict[str, str] = {
    "codigo": "Código",
    "descrip": "Descripción",
    "ccate": "Categoría",
    "cod_prv": "Proveedor",
    "precio1": "Precio 1",
    "pg1": "Precio granel",
    "barra": "Código de barras",
    "referencia": "Referencia",
    "componente": "Componente",
    "stockmin": "Stock mínimo",
    "stockmax": "Stock máximo",
    "recipe": "Receta",
    "cfrio": "Cadena frío",
    "activo": "Activo",
    "porvg": "% ganancia",
}

_NUMERIC_FIELDS = frozenset({"precio1", "pg1", "stockmin", "stockmax", "porvg"})
_INT_FIELDS = frozenset({"recipe", "cfrio", "activo"})


def _norm_num(value: object) -> float:
    if value is None:
        return 0.0
    if isinstance(value, bool):
        return float(int(value))
    if isinstance(value, (int, float)):
        return float(Decimal(str(value)).quantize(Decimal("0.000001")))
    text = str(value).strip()
    if not text:
        return 0.0
    try:
        return float(Decimal(text).quantize(Decimal("0.000001")))
    except (InvalidOperation, ValueError):
        return 0.0


def _norm_str(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def normalize_sinv_snapshot(row: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in SINV_HUB_FIELDS:
        raw = row.get(key)
        if key in _NUMERIC_FIELDS:
            out[key] = _norm_num(raw)
        elif key in _INT_FIELDS:
            out[key] = int(_norm_num(raw))
        else:
            out[key] = _norm_str(raw)
    return out


def sinv_snapshots_equal(hub_row: dict, node_row: dict) -> bool:
    """Compara porvg guardado (0 = 0; no sustituye % de categoría)."""
    return normalize_sinv_snapshot(hub_row) == normalize_sinv_snapshot(node_row)


def sinv_diff_fields(hub_row: dict, node_row: dict) -> list[str]:
    hub_n = normalize_sinv_snapshot(hub_row)
    node_n = normalize_sinv_snapshot(node_row)
    return [k for k in SINV_HUB_FIELDS if hub_n.get(k) != node_n.get(k)]


# Texto vacío en tienda que el pull puede rellenar desde el hub sin warning.
SINV_FILL_EMPTY_TEXT_FIELDS = frozenset({"barra", "referencia", "componente"})


def sinv_empty_field_patch(hub_row: dict, node_row: dict) -> dict[str, Any] | None:
    """
    Si el hub tiene datos y la tienda los tiene vacíos (p. ej. barra), devuelve
    fila parcial para upsert. None si hay conflicto real o no hay nada que rellenar.
    """
    hub_n = normalize_sinv_snapshot(hub_row)
    node_n = normalize_sinv_snapshot(node_row)
    patch: dict[str, Any] = {"codigo": hub_n["codigo"]}
    changed = False

    for key in SINV_HUB_FIELDS:
        if key == "codigo":
            continue
        hub_val = hub_n.get(key)
        node_val = node_n.get(key)
        if hub_val == node_val:
            continue
        if key in SINV_FILL_EMPTY_TEXT_FIELDS:
            if str(node_val or "").strip():
                return None
            if str(hub_val or "").strip():
                patch[key] = hub_val
                changed = True
            continue
        return None

    return patch if changed else None
