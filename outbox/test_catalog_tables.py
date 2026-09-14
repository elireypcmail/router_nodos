"""Tests de routing outbox catálogo → event names."""

from __future__ import annotations

from outbox.catalog_tables import (
    CATALOG_OUTBOX_TABLES,
    EVENT_BY_TABLE,
    catalog_entity_type,
    catalog_event_name,
)


def test_catalog_event_names():
    assert catalog_event_name("sinv") == "product.change"
    assert catalog_event_name("sprv") == "provider.change"
    assert catalog_event_name("catego") == "category.change"
    assert catalog_event_name("general") == "laboratory.change"
    assert catalog_event_name("precios") == "precios.change"
    assert catalog_event_name("costo") == "costo.change"
    assert catalog_event_name("existencia") == "existencia.change"
    assert catalog_event_name("kardex") is None


def test_catalog_entity_types():
    assert catalog_entity_type("sinv") == "product"
    assert catalog_entity_type("general") == "laboratory"
    assert catalog_entity_type("precios") == "precios"
    assert catalog_entity_type("existencia") == "existencia"


def test_catalog_tables_set():
    assert CATALOG_OUTBOX_TABLES == set(EVENT_BY_TABLE)
    assert CATALOG_OUTBOX_TABLES == {
        "sinv",
        "sprv",
        "catego",
        "general",
        "precios",
        "costo",
        "existencia",
    }
