"""Compare sinv master rows (hub vs store) for initial pull."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from sinv_store import SINV_HUB_FIELDS

SINV_FIELD_LABELS: dict[str, str] = {
    "codigo": "Code",
    "descrip": "Description",
    "ccate": "Category",
    "cod_prv": "Provider",
    "precio1": "Price 1",
    "pg1": "Bulk price",
    "barra": "Barcode",
    "referencia": "Reference",
    "componente": "Component",
    "stockmin": "Min stock",
    "stockmax": "Max stock",
    "recipe": "Recipe",
    "cfrio": "Cold chain",
    "activo": "Active",
    "porvg": "Margin pct",
}

_NUMERIC_FIELDS = frozenset({"precio1", "pg1", "stockmin", "stockmax", "porvg"})
_INT_FIELDS = frozenset({"recipe", "cfrio", "activo"})


def _norm_flag01(value: object, *, default: int = 0) -> int:
    """Normaliza flags 0/1 (bool, '1', '0', true/false)."""
    if value is None:
        return default
    if isinstance(value, bool):
        return 1 if value else 0
    if isinstance(value, (int, float)):
        return 1 if int(value) == 1 else 0
    text = str(value).strip().lower()
    if not text:
        return default
    if text in {"1", "true", "si", "yes"}:
        return 1
    if text in {"0", "false", "no"}:
        return 0
    try:
        return 1 if int(float(text)) == 1 else 0
    except (TypeError, ValueError):
        return default


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
            default = 1 if key == "activo" else 0
            out[key] = _norm_flag01(raw, default=default)
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
# Flags 0/1: el hub manda; no generar conflicto en pull (p. ej. activo).
SINV_HUB_WINS_FLAG_FIELDS = frozenset({"activo", "recipe", "cfrio"})


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
        if key in SINV_HUB_WINS_FLAG_FIELDS:
            patch[key] = hub_val
            changed = True
            continue
        return None

    return patch if changed else None
