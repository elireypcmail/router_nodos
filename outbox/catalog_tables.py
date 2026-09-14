"""Tablas outbox de catálogo / precios / costo / existencia → eventos webhook."""

from __future__ import annotations

CATALOG_OUTBOX_TABLES = frozenset(
    {"sinv", "sprv", "catego", "general", "precios", "costo", "existencia"}
)

EVENT_BY_TABLE: dict[str, str] = {
    "sinv": "product.change",
    "sprv": "provider.change",
    "catego": "category.change",
    "general": "laboratory.change",
    "precios": "precios.change",
    "costo": "costo.change",
    "existencia": "existencia.change",
}

ENTITY_TYPE_BY_TABLE: dict[str, str] = {
    "sinv": "product",
    "sprv": "provider",
    "catego": "category",
    "general": "laboratory",
    "precios": "precios",
    "costo": "costo",
    "existencia": "existencia",
}


def catalog_event_name(table_name: str) -> str | None:
    return EVENT_BY_TABLE.get(table_name)


def catalog_entity_type(table_name: str) -> str | None:
    return ENTITY_TYPE_BY_TABLE.get(table_name)
