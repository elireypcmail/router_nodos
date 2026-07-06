from __future__ import annotations

from typing import Any

MOVEMENT_OUTBOX_TABLES = frozenset({"kardex"})

# Filas legacy en cola (triggers antiguos); nuevos triggers solo escriben kardex.
LEGACY_MOVEMENT_OUTBOX_TABLES = frozenset({"comprasdbf", "diariovi"})

ALL_MOVEMENT_OUTBOX_TABLES = MOVEMENT_OUTBOX_TABLES | LEGACY_MOVEMENT_OUTBOX_TABLES


def _num(value: Any) -> float:
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def entity_type_from_row(row: dict[str, Any] | None) -> str:
    if not row:
        return "kardex"
    compras = _num(row.get("compras"))
    if compras == 0 and row.get("numdoc") is not None and row.get("cantidad") is not None:
        compras = _num(row.get("cantidad"))
    ventas = _num(row.get("ventas"))
    if ventas == 0 and row.get("numero") and not compras and row.get("cantidad") is not None:
        ventas = _num(row.get("cantidad"))
    if compras != 0:
        return "purchase"
    if ventas != 0:
        return "sale"
    return "kardex"


def resolve_entity_type(table_name: str, row: dict[str, Any] | None) -> str:
    if table_name in LEGACY_MOVEMENT_OUTBOX_TABLES:
        return {"comprasdbf": "purchase", "diariovi": "sale"}[table_name]
    if table_name == "kardex":
        return entity_type_from_row(row)
    return table_name


def normalize_source_table(table_name: str) -> str:
    if table_name in ALL_MOVEMENT_OUTBOX_TABLES:
        return "kardex"
    return table_name
