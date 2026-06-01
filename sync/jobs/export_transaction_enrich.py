"""Enriquecimiento batch para export transaccional (1 conexión + cachés por SKU)."""

from __future__ import annotations

from typing import Any

from db.mysql import MySqlClient
from db.schema_cache import TableColumnCache
from hub.catalog_snapshot import load_node_catalog_with_cursor
from outbox.purchase_lots import load_purchase_lot_snapshot
from outbox.purchase_scom import prepare_purchase_payload_for_hub
from outbox.sale_diariovi import prepare_sale_payload_for_hub


class ExportTransactionEnricher:
    """Reutiliza conexión MySQL y cachés durante export masivo de kardex."""

    def __init__(self, mysql: MySqlClient) -> None:
        self.mysql = mysql
        self.col_cache = TableColumnCache()
        self._conn = None
        self._cur = None
        self._detalle_rows: dict[str, list[dict[str, Any]]] = {}
        self._catalog: dict[str, dict[str, Any] | None] = {}
        self._catego: dict[str, dict[str, Any] | None] = {}
        self._sprv: dict[str, dict[str, Any] | None] = {}

    def __enter__(self) -> ExportTransactionEnricher:
        self._conn = self.mysql.connect()
        self._cur = self._conn.cursor(dictionary=True)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._cur is not None:
            self._cur.close()
        if self._conn is not None:
            self._conn.close()
        self._cur = None
        self._conn = None

    def enrich_purchase(self, payload: dict[str, Any]) -> dict[str, Any]:
        prep = prepare_purchase_payload_for_hub(
            payload,
            attempts=999,
            mysql=self.mysql,
            cur=self._cur,
            col_cache=self.col_cache,
        )
        out = dict(prep.payload or payload)
        codigo = str(out.get("codigo") or "").strip()
        if codigo:
            costo = float(out.get("costo_actual_factura") or out.get("precio") or 0)
            lotes = load_purchase_lot_snapshot(
                self.mysql,
                codigo,
                preferred_costo=costo or None,
                preferred_costopro=costo or None,
                cur=self._cur,
                detalle_rows_cache=self._detalle_rows,
            )
            if lotes:
                out["lotes"] = lotes
            catalog = load_node_catalog_with_cursor(
                self._cur,
                codigo,
                product_cache=self._catalog,
                catego_cache=self._catego,
                provider_cache=self._sprv,
            )
            if catalog:
                out["node_catalog"] = catalog
        return out

    def enrich_sale(self, payload: dict[str, Any]) -> dict[str, Any]:
        prep = prepare_sale_payload_for_hub(
            payload,
            mysql=self.mysql,
            cur=self._cur,
            col_cache=self.col_cache,
        )
        out = dict(prep.payload or payload)
        codigo = str(out.get("codigo") or "").strip()
        if codigo:
            catalog = load_node_catalog_with_cursor(
                self._cur,
                codigo,
                product_cache=self._catalog,
                catego_cache=self._catego,
                provider_cache=self._sprv,
            )
            if catalog:
                out["node_catalog"] = catalog
        return out
