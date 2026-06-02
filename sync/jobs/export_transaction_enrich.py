"""Enriquecimiento batch para export transaccional (1 conexión + cachés por SKU)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from db.mysql import MySqlClient
from db.schema_cache import TableColumnCache
from hub.catalog_snapshot import load_node_catalog_with_cursor
from outbox.purchase_lots import load_purchase_lot_snapshot
from outbox.purchase_scom import prepare_purchase_payload_for_hub
from outbox.purchase_scom_index import PurchaseScomIndex, build_purchase_scom_index
from outbox.sale_diariovi import prepare_sale_payload_for_hub
from outbox.sale_erp_index import (
    SaleErpLineIndex,
    build_sale_erp_line_index,
    build_sale_erp_line_index_from_kardex_keys,
)
from sync.jobs.kardex_sale_scope import collect_kardex_sale_lookup_keys
from sync.jobs.node_stock_snapshot import attach_node_stock_fields
from sync.jobs.transaction_sync_types import TransactionWatermark


class ExportTransactionEnricher:
    """Reutiliza conexión MySQL, índices ERP y cachés durante export masivo."""

    def __init__(
        self,
        mysql: MySqlClient,
        *,
        bulk_file_export: bool = False,
    ) -> None:
        self.mysql = mysql
        self.bulk_file_export = bulk_file_export
        self.col_cache = TableColumnCache()
        self._conn = None
        self._cur = None
        self._detalle_rows: dict[str, list[dict[str, Any]]] = {}
        self._catalog: dict[str, dict[str, Any] | None] = {}
        self._catego: dict[str, dict[str, Any] | None] = {}
        self._sprv: dict[str, dict[str, Any] | None] = {}
        self._scom_index: PurchaseScomIndex | None = None
        self._diariovi_index: SaleErpLineIndex | None = None

    def __enter__(self) -> ExportTransactionEnricher:
        self._conn = self.mysql.connect_bulk_export()
        self._cur = self._conn.cursor(dictionary=True)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._cur is not None:
            self._cur.close()
        if self._conn is not None:
            self._conn.close()
        self._cur = None
        self._conn = None

    def warm_purchase_scom_index(self, codigo_filter: str | None = None) -> int:
        if self._cur is None:
            return 0
        if self._scom_index is None:
            self._scom_index = build_purchase_scom_index(
                self._cur,
                col_cache=self.col_cache,
                codigo_filter=codigo_filter,
            )
        return self._scom_index.row_count

    def warm_sale_diariovi_index(
        self,
        codigo_filter: str | None = None,
        *,
        since_watermark: TransactionWatermark | None = None,
        kardex_rows: int = 0,
        on_prepare_pct: Callable[[int], None] | None = None,
    ) -> int:
        if self._cur is None:
            return 0
        if self._diariovi_index is not None:
            return self._diariovi_index.row_count
        if on_prepare_pct is not None:
            on_prepare_pct(1)
        if codigo_filter:
            self._diariovi_index = build_sale_erp_line_index(
                self._cur,
                "diariovi",
                col_cache=self.col_cache,
                codigo_filter=codigo_filter,
            )
            if on_prepare_pct is not None:
                on_prepare_pct(8)
        else:
            keys = collect_kardex_sale_lookup_keys(
                self._cur,
                self.col_cache,
                codigo=None,
                since_watermark=since_watermark,
                on_rows_read=(
                    None
                    if on_prepare_pct is None or kardex_rows <= 0
                    else lambda n: on_prepare_pct(
                        2 + min(3, int(3 * n / max(1, kardex_rows)))
                    )
                ),
            )
            diariovi_cols = self.col_cache.columns(self._cur, "diariovi")

            def _on_queries(done: int, total: int) -> None:
                if on_prepare_pct is None or total <= 0:
                    return
                on_prepare_pct(5 + min(3, int(3 * done / total)))

            self._diariovi_index = build_sale_erp_line_index_from_kardex_keys(
                self._cur,
                "diariovi",
                keys,
                col_cache=self.col_cache,
                on_query_done=_on_queries if on_prepare_pct else None,
            )
            if on_prepare_pct is not None:
                on_prepare_pct(8)
        return self._diariovi_index.row_count

    def enrich_purchase(self, payload: dict[str, Any]) -> dict[str, Any]:
        prep = prepare_purchase_payload_for_hub(
            payload,
            attempts=999,
            mysql=self.mysql,
            cur=self._cur,
            col_cache=self.col_cache,
            scom_index=self._scom_index,
        )
        out = dict(prep.payload or payload)
        codigo = str(out.get("codigo") or "").strip()
        if not codigo or self.bulk_file_export:
            return out
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
        return attach_node_stock_fields(
            out,
            mysql=self.mysql,
            cur=self._cur,
            codigo=codigo,
            detalle_rows_cache=self._detalle_rows,
            preferred_costo=costo or None,
            preferred_costopro=costo or None,
        )

    def enrich_sale(self, payload: dict[str, Any]) -> dict[str, Any]:
        prep = prepare_sale_payload_for_hub(
            payload,
            mysql=self.mysql,
            cur=self._cur,
            col_cache=self.col_cache,
            diariovi_index=self._diariovi_index,
        )
        out = dict(prep.payload or payload)
        if self.bulk_file_export:
            return out
        codigo = str(out.get("codigo") or "").strip()
        if not codigo:
            return out
        catalog = load_node_catalog_with_cursor(
            self._cur,
            codigo,
            product_cache=self._catalog,
            catego_cache=self._catego,
            provider_cache=self._sprv,
        )
        if catalog:
            out["node_catalog"] = catalog
        return attach_node_stock_fields(
            out,
            mysql=self.mysql,
            cur=self._cur,
            codigo=codigo,
            detalle_rows_cache=self._detalle_rows,
        )

    def enrich_kardex_adjustment(self, payload: dict[str, Any]) -> dict[str, Any]:
        out = dict(payload)
        codigo = str(out.get("codigo") or "").strip()
        if not codigo or self._cur is None or self.bulk_file_export:
            return out
        return attach_node_stock_fields(
            out,
            mysql=self.mysql,
            cur=self._cur,
            codigo=codigo,
            detalle_rows_cache=self._detalle_rows,
        )
