from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Any

from core.json_util import json_safe
from db.mysql import MySqlClient
from outbox.purchase_lots import load_purchase_lot_snapshot
from outbox.purchase_scom import prepare_purchase_payload_for_hub
from outbox.sale_diariovi import prepare_sale_payload_for_hub
from hub.catalog_snapshot import load_node_catalog
from sync.jobs.transaction_sync_types import (
    TransactionWatermark,
    max_watermark_from_rows,
)


def _num(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip())
    except Exception:
        return 0.0


def _job_file(job_id: str) -> Path:
    from sync.jobs.files import job_file_path

    return job_file_path(job_id)


def _row_event_id(
    mode: str,
    row: dict[str, Any],
) -> str:
    indice = str(row.get("indice") or "").strip()
    if indice:
        return f"{mode}-kardex-{indice}"
    contador = str(row.get("contador") or "").strip()
    numero = str(row.get("numero") or "").strip()
    fecha = str(row.get("fecha") or "").strip()[:10]
    codigo = str(row.get("codigo") or "").strip()
    return f"{mode}-kardex-fallback-{contador or '-'}-{numero or '-'}-{fecha or '-'}-{codigo or '-'}"


def _apply_watermark_filter(
    where_parts: list[str],
    params: list[Any],
    watermark: TransactionWatermark | None,
    *,
    has_fecha: bool,
    has_contador: bool,
) -> None:
    if watermark is None or not has_fecha:
        return
    if has_contador and watermark.contador is not None:
        where_parts.append(
            "(fecha > %s OR (fecha = %s AND IFNULL(contador, 0) > %s))"
        )
        params.extend([watermark.fecha, watermark.fecha, watermark.contador])
    else:
        where_parts.append("fecha > %s")
        params.append(watermark.fecha)


def _iter_kardex_rows(
    mysql: MySqlClient,
    *,
    mode: str,
    codigo: str | None,
    since_watermark: TransactionWatermark | None = None,
) -> list[dict[str, Any]]:
    where_parts: list[str] = []
    params: list[Any] = []
    if mode == "purchase":
        where_parts.append("IFNULL(compras, 0) <> 0")
    else:
        where_parts.append("IFNULL(ventas, 0) <> 0")
    if codigo:
        where_parts.append("TRIM(codigo) = %s")
        params.append(codigo.strip())
    conn = mysql.connect()
    try:
        with conn.cursor(dictionary=True) as cur:
            cur.execute("SHOW COLUMNS FROM kardex")
            columns = {
                str((row or {}).get("Field") or "").strip().lower()
                for row in (cur.fetchall() or [])
                if isinstance(row, dict)
            }

            has_fecha = "fecha" in columns
            has_indice = "indice" in columns
            has_contador = "contador" in columns

            _apply_watermark_filter(
                where_parts,
                params,
                since_watermark,
                has_fecha=has_fecha,
                has_contador=has_contador,
            )

            indice_select = "indice" if has_indice else "NULL"
            if has_fecha and has_indice:
                order_by = "fecha ASC, indice ASC, numero ASC, codigo ASC"
            elif has_fecha and has_contador:
                order_by = "fecha ASC, contador ASC, numero ASC, codigo ASC"
            elif has_fecha:
                order_by = "fecha ASC, numero ASC, codigo ASC"
            elif has_indice:
                order_by = "indice ASC"
            elif has_contador:
                order_by = "contador ASC, numero ASC, codigo ASC"
            else:
                order_by = "numero ASC, codigo ASC"

            where = " AND ".join(where_parts)
            query = f"""
                SELECT {indice_select} AS indice, contador, numero, codigo, fecha, costo, compras, ventas, cajero, kobs
                FROM kardex
                WHERE {where}
                ORDER BY {order_by}
            """
            cur.execute(query, tuple(params))
            return list(cur.fetchall() or [])
    finally:
        conn.close()


def _purchase_payload(row: dict[str, Any]) -> dict[str, Any]:
    compras = _num(row.get("compras"))
    costo = _num(row.get("costo"))
    return {
        "contador": row.get("contador") or row.get("indice"),
        "numdoc": str(row.get("numero") or "").strip(),
        "codigo": str(row.get("codigo") or "").strip(),
        "cantidad": compras,
        "precio": costo,
        "monto": round(compras * costo, 2),
        "costo_actual_factura": costo,
        "fecha": row.get("fecha"),
        "kobs": row.get("kobs"),
        "kardex_indice": row.get("indice"),
    }


def _sale_payload(row: dict[str, Any]) -> dict[str, Any]:
    ventas = _num(row.get("ventas"))
    return {
        "numero": str(row.get("numero") or "").strip(),
        "codigo": str(row.get("codigo") or "").strip(),
        "contador": row.get("contador") or row.get("indice"),
        "ccaja": str(row.get("cajero") or "").strip(),
        "fecha": row.get("fecha"),
        "cantidad": ventas,
        "kardex_indice": row.get("indice"),
    }


def export_transaction_push_file(
    job_id: str,
    mysql: MySqlClient,
    nodo_id: str,
    *,
    mode: str,
    codigo: str | None = None,
    since_watermark: TransactionWatermark | None = None,
    should_cancel=None,
    on_progress=None,
) -> tuple[Path, int, dict[str, Any]]:
    """
    Crea archivo .ndjson.gz para push transaccional:
    - mode="purchase" -> entity_type purchase
    - mode="sale" -> entity_type sale

    since_watermark: filtro desde hub (None = exportar todo).
    """
    if mode not in {"purchase", "sale"}:
        raise RuntimeError("mode must be purchase|sale")

    path = _job_file(job_id)
    tmp = Path(f"{path}.tmp")
    rows = _iter_kardex_rows(
        mysql,
        mode=mode,
        codigo=codigo,
        since_watermark=since_watermark,
    )
    total = len(rows)
    written = 0
    max_watermark = max_watermark_from_rows(rows)

    if on_progress and total >= 0:
        on_progress(0, total, 0)

    with gzip.open(tmp, "wt", encoding="utf-8") as gz:
        manifest = {
            "v": 1,
            "direction": "push",
            "entity": mode,
            "nodoId": nodo_id,
            "totalRows": total,
            "schema": f"{mode}_v1",
            "codigo": (codigo or "").strip() or None,
            "sinceWatermark": since_watermark.to_dict() if since_watermark else None,
        }
        gz.write(json.dumps(manifest, ensure_ascii=True) + "\n")

        for row in rows:
            if should_cancel:
                should_cancel()
            if mode == "purchase":
                payload = _purchase_payload(row)
                prep = prepare_purchase_payload_for_hub(payload, attempts=999, mysql=mysql)
                payload = prep.payload or payload
                lotes = load_purchase_lot_snapshot(
                    mysql,
                    str(payload.get("codigo") or ""),
                    preferred_costo=_num(payload.get("costo_actual_factura"))
                    or _num(payload.get("precio")),
                    preferred_costopro=_num(payload.get("costo_actual_factura"))
                    or _num(payload.get("precio")),
                )
                if lotes:
                    payload["lotes"] = lotes
            else:
                payload = _sale_payload(row)
                payload = prepare_sale_payload_for_hub(payload, mysql=mysql).payload

            codigo_payload = str(payload.get("codigo") or "").strip()
            if codigo_payload:
                catalog = load_node_catalog(codigo_payload)
                if catalog:
                    payload["node_catalog"] = catalog

            event = json_safe(
                {
                    "entity_type": mode,
                    "event_id": _row_event_id(mode, row),
                    "payload": json_safe(payload),
                    "occurred_at": row.get("fecha"),
                }
            )
            gz.write(json.dumps(event, ensure_ascii=True) + "\n")
            written += 1
            if on_progress and total > 0:
                pct = int((written / total) * 100)
                on_progress(written, total, pct)

    tmp.replace(path)
    meta = {
        "since_watermark": since_watermark.to_dict() if since_watermark else None,
        "max_watermark": max_watermark.to_dict() if max_watermark else None,
    }
    return path, total, meta
