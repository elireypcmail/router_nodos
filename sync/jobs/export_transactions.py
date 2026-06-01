from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Any

from core.json_util import json_safe
from db.mysql import MySqlClient
from db.schema_cache import TableColumnCache
from sync.jobs.export_transaction_enrich import ExportTransactionEnricher
from sync.jobs.node_stock_snapshot import append_stock_snapshot_lines
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
    col_cache = TableColumnCache()
    try:
        with conn.cursor(dictionary=True) as cur:
            kardex_cols = col_cache.columns(cur, "kardex")
            has_fecha = "fecha" in kardex_cols
            has_indice = "indice" in kardex_cols
            has_contador = "contador" in kardex_cols

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


def _iter_kardex_adjustment_rows(
    mysql: MySqlClient,
    *,
    codigo: str | None,
    since_watermark: TransactionWatermark | None = None,
) -> list[dict[str, Any]]:
    """Ajustes y devoluciones (sin compra/venta en el renglón)."""
    where_parts: list[str] = [
        "IFNULL(compras, 0) = 0",
        "IFNULL(ventas, 0) = 0",
        (
            "(IFNULL(ajustesp, 0) <> 0 OR IFNULL(ajustesn, 0) <> 0 "
            "OR IFNULL(devoc, 0) <> 0 OR IFNULL(devov, 0) <> 0)"
        ),
    ]
    params: list[Any] = []
    if codigo:
        where_parts.append("TRIM(codigo) = %s")
        params.append(codigo.strip())
    conn = mysql.connect()
    col_cache = TableColumnCache()
    try:
        with conn.cursor(dictionary=True) as cur:
            kardex_cols = col_cache.columns(cur, "kardex")
            has_fecha = "fecha" in kardex_cols
            has_indice = "indice" in kardex_cols
            has_contador = "contador" in kardex_cols
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
            else:
                order_by = "numero ASC, codigo ASC"
            where = " AND ".join(where_parts)
            query = f"""
                SELECT {indice_select} AS indice, contador, numero, codigo, fecha,
                       compras, ventas, ajustesp, ajustesn, devoc, devov, costo, kobs
                FROM kardex
                WHERE {where}
                ORDER BY {order_by}
            """
            cur.execute(query, tuple(params))
            return list(cur.fetchall() or [])
    finally:
        conn.close()


def _kardex_adjustment_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "contador": row.get("contador") or row.get("indice"),
        "codigo": str(row.get("codigo") or "").strip(),
        "fecha": row.get("fecha"),
        "numdoc": str(row.get("numero") or "").strip(),
        "compras": _num(row.get("compras")),
        "ventas": _num(row.get("ventas")),
        "ajustesp": _num(row.get("ajustesp")),
        "ajustesn": _num(row.get("ajustesn")),
        "devoc": _num(row.get("devoc")),
        "devov": _num(row.get("devov")),
        "costo": _num(row.get("costo")),
        "kobs": row.get("kobs"),
        "kardex_indice": row.get("indice"),
    }


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
    adjustment_rows = _iter_kardex_adjustment_rows(
        mysql,
        codigo=codigo,
        since_watermark=since_watermark,
    )
    codigos_seen: set[str] = set()
    for r in rows:
        c = str(r.get("codigo") or "").strip()
        if c:
            codigos_seen.add(c)
    for r in adjustment_rows:
        c = str(r.get("codigo") or "").strip()
        if c:
            codigos_seen.add(c)
    total = len(rows) + len(adjustment_rows) + len(codigos_seen)
    written = 0
    max_watermark = max_watermark_from_rows(rows + adjustment_rows)

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
            "maxWatermark": {
                mode: max_watermark.to_dict() if max_watermark else None,
            },
        }
        gz.write(json.dumps(manifest, ensure_ascii=True) + "\n")

        progress_stride = max(total // 100, 1) if total > 0 else 1
        with ExportTransactionEnricher(mysql) as enricher:
            for row in rows:
                if should_cancel:
                    should_cancel()
                if mode == "purchase":
                    payload = enricher.enrich_purchase(_purchase_payload(row))
                else:
                    payload = enricher.enrich_sale(_sale_payload(row))

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
                if on_progress and total > 0 and (
                    written == total
                    or written == 1
                    or written % progress_stride == 0
                ):
                    pct = int((written / total) * 100)
                    on_progress(written, total, pct)

            for row in adjustment_rows:
                if should_cancel:
                    should_cancel()
                payload = enricher.enrich_kardex_adjustment(
                    _kardex_adjustment_payload(row)
                )
                event = json_safe(
                    {
                        "entity_type": "kardex",
                        "event_id": _row_event_id("kardex", row),
                        "payload": json_safe(payload),
                        "occurred_at": row.get("fecha"),
                    }
                )
                gz.write(json.dumps(event, ensure_ascii=True) + "\n")
                written += 1

            snapshot_rows = append_stock_snapshot_lines(
                gz,
                mysql=mysql,
                cur=enricher._cur,
                nodo_id=nodo_id,
                codigos=codigos_seen,
                job_tag=job_id,
                detalle_rows_cache=enricher._detalle_rows,
                since_watermark=(
                    since_watermark.to_dict() if since_watermark else None
                ),
            )
            written += snapshot_rows

    tmp.replace(path)
    meta = {
        "file_rows": total,
        "since_watermark": since_watermark.to_dict() if since_watermark else None,
        "max_watermark": max_watermark.to_dict() if max_watermark else None,
    }
    return path, total, meta
