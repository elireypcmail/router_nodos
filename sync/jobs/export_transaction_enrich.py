"""Enriquecimiento batch para export transaccional (1 conexión + índices ERP).

No adjunta maestro de catálogo (sinv/catego/sprv): el hub valida por codigo kardex.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from db.mysql import MySqlClient
from db.schema_cache import TableColumnCache
from outbox.purchase_scom import prepare_purchase_payload_for_hub
from outbox.purchase_scom_index import PurchaseScomIndex, build_purchase_scom_index
from outbox.sale_diariovi import prepare_sale_payload_for_hub
from outbox.sale_erp_index import (
    SaleErpLineIndex,
    build_merged_sale_erp_index_from_kardex_join,
)
from sync.jobs.kardex_sale_scope import build_kardex_ventas_where
from sync.jobs.transaction_sync_types import TransactionWatermark


class ExportTransactionEnricher:
    """Reutiliza conexión MySQL e índices ERP durante export transaccional masivo."""

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
        k_where, k_params = build_kardex_ventas_where(
            self.col_cache,
            self._cur,
            codigo=codigo_filter,
            since_watermark=since_watermark,
        )

        def _on_batch(table: str, _rows: int) -> None:
            if on_prepare_pct is None:
                return
            if table == "diariovi":
                on_prepare_pct(5)
            elif table == "ventasi":
                on_prepare_pct(7)

        self._diariovi_index = build_merged_sale_erp_index_from_kardex_join(
            self._cur,
            col_cache=self.col_cache,
            kardex_where_parts=k_where,
            kardex_params=tuple(k_params),
            erp_codigo_filter=codigo_filter,
            on_batch=_on_batch if on_prepare_pct else None,
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
        return dict(prep.payload or payload)

    def enrich_sale(self, payload: dict[str, Any]) -> dict[str, Any]:
        prep = prepare_sale_payload_for_hub(
            payload,
            mysql=self.mysql,
            cur=self._cur,
            col_cache=self.col_cache,
            diariovi_index=self._diariovi_index,
        )
        return dict(prep.payload or payload)

    def enrich_kardex_adjustment(self, payload: dict[str, Any]) -> dict[str, Any]:
        return dict(payload)
