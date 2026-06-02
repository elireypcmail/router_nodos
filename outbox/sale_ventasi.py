"""Enriquece ventas del outbox con línea ERP sellada en ventasi (precio1, subtotal2)."""

from __future__ import annotations

from typing import Any

from db.mysql import MySqlClient
from db.schema_cache import TableColumnCache
from outbox.sale_erp_line import lookup_sale_line_in_table


def lookup_ventasi_sale_line(
    mysql: MySqlClient,
    payload: dict[str, Any],
    *,
    cur: Any | None = None,
    col_cache: TableColumnCache | None = None,
) -> dict[str, Any] | None:
    return lookup_sale_line_in_table(
        mysql,
        payload,
        table="ventasi",
        cur=cur,
        col_cache=col_cache,
    )
