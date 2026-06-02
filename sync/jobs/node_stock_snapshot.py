"""Stock actual del nodo (sinv + detalle) para sync transaccional al hub."""

from __future__ import annotations

from typing import Any

from outbox.purchase_lots import load_purchase_lot_snapshot


def _to_float(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip())
    except Exception:
        return 0.0


def load_sinv_existencia(cur: Any, codigo: str) -> float | None:
    key = str(codigo or "").strip()
    if not key:
        return None
    cur.execute(
        "SELECT COALESCE(existencia, 0) AS existencia FROM sinv WHERE codigo = %s LIMIT 1",
        (key,),
    )
    row = cur.fetchone()
    if not row:
        return None
    return _to_float(row.get("existencia"))


def attach_node_stock_fields(
    payload: dict[str, Any],
    *,
    mysql: Any,
    cur: Any,
    codigo: str,
    detalle_rows_cache: dict[str, list[dict[str, Any]]] | None = None,
    preferred_costo: float | None = None,
    preferred_costopro: float | None = None,
) -> dict[str, Any]:
    """Añade existencia_nodo y lotes (detalle) al payload de compra/venta/kardex."""
    out = dict(payload)
    key = str(codigo or out.get("codigo") or "").strip()
    if not key:
        return out

    existencia = load_sinv_existencia(cur, key)
    if existencia is not None:
        out["existencia_nodo"] = existencia

    if not out.get("lotes"):
        lotes = load_purchase_lot_snapshot(
            mysql,
            key,
            preferred_costo=preferred_costo,
            preferred_costopro=preferred_costopro,
            cur=cur,
            detalle_rows_cache=detalle_rows_cache,
        )
        if lotes:
            out["lotes"] = lotes

    return out


def build_stock_snapshot_payload(
    mysql: Any,
    cur: Any,
    codigo: str,
    *,
    detalle_rows_cache: dict[str, list[dict[str, Any]]] | None = None,
    since_watermark: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    key = str(codigo or "").strip()
    if not key:
        return None
    existencia = load_sinv_existencia(cur, key)
    if existencia is None:
        return None
    lotes = load_purchase_lot_snapshot(
        mysql,
        key,
        cur=cur,
        detalle_rows_cache=detalle_rows_cache,
    )
    out: dict[str, Any] = {
        "codigo": key,
        "existencia_nodo": existencia,
        "lotes": lotes,
    }
    if since_watermark:
        out["since_watermark"] = since_watermark
    return out


def append_stock_snapshot_lines(
    gz: Any,
    *,
    mysql: Any,
    cur: Any,
    nodo_id: str,
    codigos: set[str],
    job_tag: str,
    detalle_rows_cache: dict[str, list[dict[str, Any]]] | None = None,
    since_watermark: dict[str, Any] | None = None,
) -> int:
    """Escribe eventos stock_snapshot al final del .ndjson.gz (reconciliación ERP)."""
    import json

    from core.json_util import json_safe

    from sync.jobs.ingest_event_ids import bounded_event_id

    written = 0
    for codigo in sorted(codigos):
        snap = build_stock_snapshot_payload(
            mysql,
            cur,
            codigo,
            detalle_rows_cache=detalle_rows_cache,
            since_watermark=since_watermark,
        )
        if not snap:
            continue
        event = json_safe(
            {
                "entity_type": "stock_snapshot",
                "event_id": bounded_event_id("stock-snap", job_tag, codigo),
                "payload": snap,
            }
        )
        gz.write(json.dumps(event, ensure_ascii=True) + "\n")
        written += 1
    return written
