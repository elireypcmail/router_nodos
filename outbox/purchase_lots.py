"""Adjunta lotes actuales desde detalle al payload de compra (outbox -> hub)."""

from __future__ import annotations

from typing import Any

from db.mysql import MySqlClient

_DETALLE_SELECT = """
    SELECT
      codigod,
      lote,
      cubica,
      vence,
      existencia,
      costo,
      costopro,
      calidad,
      elabora
    FROM detalle
    WHERE TRIM(codigo) = %s
    ORDER BY cubica ASC, lote ASC, vence ASC
"""


def _to_float(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip())
    except Exception:
        return 0.0


def _to_date(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    if not s or s == "0000-00-00":
        return None
    return s[:10]


def _fetch_detalle_rows(cur: Any, codigo: str) -> list[dict[str, Any]]:
    cur.execute(_DETALLE_SELECT, (codigo,))
    return list(cur.fetchall() or [])


def _build_lot_snapshot_from_rows(
    rows: list[dict[str, Any]],
    *,
    preferred_costo: float | None = None,
    preferred_costopro: float | None = None,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    preferred_costo_value = _to_float(preferred_costo)
    preferred_costopro_value = _to_float(preferred_costopro)
    for r in rows:
        costo_detalle = _to_float(r.get("costo"))
        costopro_detalle = _to_float(r.get("costopro"))
        costo_final = preferred_costo_value or costo_detalle
        costopro_final = (
            preferred_costopro_value
            or preferred_costo_value
            or costopro_detalle
            or costo_final
        )
        lote = str(r.get("lote") or "").strip()
        codigod = str(r.get("codigod") or "").strip()
        calidad = str(r.get("calidad") or "").strip()
        out.append(
            {
                "lote": lote,
                "codigod": codigod or lote,
                "cubica": str(r.get("cubica") or "").strip(),
                "vence": _to_date(r.get("vence")),
                "existencia": _to_float(r.get("existencia")),
                "costo": costo_final,
                "costopro": costopro_final,
                "calidad": calidad if r.get("calidad") is not None else None,
                "elabora": _to_date(r.get("elabora")),
            }
        )
    return out


def load_purchase_lot_snapshot(
    mysql: MySqlClient | None,
    codigo: str,
    *,
    preferred_costo: float | None = None,
    preferred_costopro: float | None = None,
    cur: Any | None = None,
    detalle_rows_cache: dict[str, list[dict[str, Any]]] | None = None,
) -> list[dict[str, Any]]:
    """Lee detalle por SKU y devuelve snapshot normalizado para hub ingest."""
    key = str(codigo or "").strip()
    if not mysql or not mysql.is_configured() or not key:
        return []

    def _rows_from_cache_or_db(active_cur: Any) -> list[dict[str, Any]]:
        if detalle_rows_cache is not None:
            if key not in detalle_rows_cache:
                detalle_rows_cache[key] = _fetch_detalle_rows(active_cur, key)
            return detalle_rows_cache[key]
        return _fetch_detalle_rows(active_cur, key)

    if cur is not None:
        rows = _rows_from_cache_or_db(cur)
        return _build_lot_snapshot_from_rows(
            rows,
            preferred_costo=preferred_costo,
            preferred_costopro=preferred_costopro,
        )

    conn = mysql.connect()
    try:
        active_cur = conn.cursor(dictionary=True)
        rows = _rows_from_cache_or_db(active_cur)
        return _build_lot_snapshot_from_rows(
            rows,
            preferred_costo=preferred_costo,
            preferred_costopro=preferred_costopro,
        )
    finally:
        conn.close()
