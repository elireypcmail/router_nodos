"""Utilidades compartidas: ventasi / diariovi → payload sale para el hub."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from db.mysql import MySqlClient
from db.schema_cache import TableColumnCache


def _to_float(value: Any) -> float:
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _parse_fecha(raw: Any) -> date | None:
    if raw is None:
        return None
    if isinstance(raw, date) and not isinstance(raw, datetime):
        return raw
    text = str(raw).strip()[:10]
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _get_row_value(row: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in row and row.get(key) is not None:
            return row.get(key)
    return None


def _table_has_column(
    cur: Any,
    table: str,
    column: str,
    *,
    col_cache: TableColumnCache | None = None,
) -> bool:
    if col_cache is not None:
        return col_cache.has_column(cur, table, column)
    cur.execute(f"SHOW COLUMNS FROM `{table}`")
    rows = cur.fetchall() or []
    for row in rows:
        if not isinstance(row, dict):
            continue
        field = str(row.get("Field") or "").strip().lower()
        if field == column.strip().lower():
            return True
    return False


def _order_by_sale_line(table: str, cur: Any, *, col_cache: TableColumnCache | None) -> str:
    has_fecha = _table_has_column(cur, table, "fecha", col_cache=col_cache)
    has_indice = _table_has_column(cur, table, "indice", col_cache=col_cache)
    has_contador = _table_has_column(cur, table, "contador", col_cache=col_cache)
    if has_fecha and has_indice:
        return "fecha DESC, indice DESC, numero DESC"
    if has_fecha and has_contador:
        return "fecha DESC, contador DESC, numero DESC"
    if has_fecha:
        return "fecha DESC, numero DESC"
    if has_indice:
        return "indice DESC, numero DESC"
    if has_contador:
        return "contador DESC, numero DESC"
    return "numero DESC"


def _fetch_sale_line_by_contador(
    cur: Any,
    *,
    table: str,
    codigo: str,
    contador: int,
    col_cache: TableColumnCache | None = None,
) -> dict[str, Any] | None:
    if not _table_has_column(cur, table, "contador", col_cache=col_cache):
        return None
    order_by = _order_by_sale_line(table, cur, col_cache=col_cache)
    cur.execute(
        f"""
        SELECT *
        FROM `{table}`
        WHERE codigo = %s
          AND contador = %s
        ORDER BY {order_by}
        LIMIT 1
        """,
        (codigo, contador),
    )
    return cur.fetchone()


def _fetch_sale_line_by_numero(
    cur: Any,
    *,
    table: str,
    codigo: str,
    numero: str,
    cantidad: float | None = None,
    col_cache: TableColumnCache | None = None,
) -> dict[str, Any] | None:
    order_by = _order_by_sale_line(table, cur, col_cache=col_cache)
    if cantidad is not None and cantidad > 0:
        cur.execute(
            f"""
            SELECT *
            FROM `{table}`
            WHERE codigo = %s
              AND numero = %s
              AND ABS(IFNULL(cantidad, 0) - %s) < 0.001
            ORDER BY {order_by}
            LIMIT 1
            """,
            (codigo, numero[:30], cantidad),
        )
        row = cur.fetchone()
        if row:
            return row
    cur.execute(
        f"""
        SELECT *
        FROM `{table}`
        WHERE codigo = %s
          AND numero = %s
        ORDER BY {order_by}
        LIMIT 1
        """,
        (codigo, numero[:30]),
    )
    return cur.fetchone()


def _fetch_sale_line_by_match(
    cur: Any,
    *,
    table: str,
    codigo: str,
    fecha: date,
    cantidad: float,
    col_cache: TableColumnCache | None = None,
) -> dict[str, Any] | None:
    order_by = _order_by_sale_line(table, cur, col_cache=col_cache)
    cur.execute(
        f"""
        SELECT *
        FROM `{table}`
        WHERE codigo = %s
          AND fecha = %s
          AND ABS(IFNULL(cantidad, 0) - %s) < 0.001
        ORDER BY {order_by}
        LIMIT 1
        """,
        (codigo, fecha, cantidad),
    )
    return cur.fetchone()


def lookup_sale_line_in_table(
    mysql: MySqlClient,
    payload: dict[str, Any],
    *,
    table: str,
    cur: Any | None = None,
    col_cache: TableColumnCache | None = None,
) -> dict[str, Any] | None:
    codigo = str(payload.get("codigo") or "").strip()
    if not codigo:
        return None

    def _lookup(active_cur: Any) -> dict[str, Any] | None:
        numero = str(payload.get("numero") or payload.get("numdoc") or "").strip()
        cantidad = _to_float(payload.get("cantidad"))

        if numero and cantidad != 0:
            row = _fetch_sale_line_by_numero(
                active_cur,
                table=table,
                codigo=codigo,
                numero=numero,
                cantidad=abs(cantidad),
                col_cache=col_cache,
            )
            if row:
                return row

        contador_raw = payload.get("contador")
        if contador_raw is not None and str(contador_raw).strip() != "":
            try:
                contador = int(contador_raw)
            except (TypeError, ValueError):
                contador = None
            if contador is not None:
                row = _fetch_sale_line_by_contador(
                    active_cur,
                    table=table,
                    codigo=codigo,
                    contador=contador,
                    col_cache=col_cache,
                )
                if row:
                    return row

        if numero:
            row = _fetch_sale_line_by_numero(
                active_cur,
                table=table,
                codigo=codigo,
                numero=numero,
                cantidad=None,
                col_cache=col_cache,
            )
            if row:
                return row

        return None

    if cur is not None:
        return _lookup(cur)

    conn = mysql.connect()
    try:
        with conn.cursor(dictionary=True) as active_cur:
            return _lookup(active_cur)
    finally:
        conn.close()


def erp_sale_unit_price(line: dict[str, Any]) -> float:
    """precio1; en diariovi/ventasi la columna costo suele ser precio unitario de venta."""
    return _to_float(
        _get_row_value(line, "precio1", "precio", "nprecio1", "pventa", "costo")
    )


def erp_sale_line_monto(line: dict[str, Any]) -> float:
    return _to_float(
        _get_row_value(line, "subtotal2", "subtotal1", "total", "subtotal", "monto")
    )


def erp_sale_line_has_pricing(line: dict[str, Any]) -> bool:
    return erp_sale_unit_price(line) > 0 or erp_sale_line_monto(line) > 0


def apply_erp_sale_line_to_payload(
    payload: dict[str, Any],
    line: dict[str, Any],
    *,
    source: str,
) -> dict[str, Any]:
    """Aplica precio unitario y subtotal sellado (subtotal2) de ventasi/diariovi."""
    out = dict(payload)

    numero = str(_get_row_value(line, "numero") or "").strip()
    if numero:
        out["numero"] = numero
        out["numdoc"] = numero

    precio = erp_sale_unit_price(line)
    if precio:
        out["precio"] = precio

    monto = erp_sale_line_monto(line)
    if monto:
        out["monto"] = monto
        if _to_float(line.get("subtotal2")):
            out["monto_source"] = f"{source}.subtotal2"
        elif _to_float(line.get("subtotal1")):
            out["monto_source"] = f"{source}.subtotal1"
        else:
            out["monto_source"] = f"{source}.line_total"
    elif precio and _to_float(out.get("cantidad")):
        out["monto"] = round(_to_float(out.get("cantidad")) * precio, 2)
        out["monto_source"] = f"{source}.cantidad_x_precio"

    indice = _get_row_value(line, "indice")
    if indice is not None:
        out[f"{source}_indice"] = str(indice).strip()

    contador = _get_row_value(line, "contador")
    if contador is not None:
        out["ventasi_contador"] = contador

    ccaja = str(_get_row_value(line, "ccaja", "cajero") or "").strip()
    if ccaja:
        out["ccaja"] = ccaja

    return out
