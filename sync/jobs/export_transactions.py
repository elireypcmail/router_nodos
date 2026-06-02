from __future__ import annotations

import gzip
import json
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.json_util import json_safe
from core.categoria_trace import trace
from db.mysql import MySqlClient
from db.schema_cache import TableColumnCache
from sync.jobs.export_transaction_enrich import ExportTransactionEnricher
from sync.jobs.kardex_sale_scope import (
    apply_kardex_watermark_filter,
    build_kardex_ventas_where,
)
from sync.jobs.node_stock_snapshot import append_stock_snapshot_lines
from sync.jobs.transaction_sync_types import (
    TransactionWatermark,
    merge_watermark,
)

KARDEX_FETCH_BATCH = 5000
# 1–8 %: preparación MySQL (claves kardex + índice diariovi); 9–94 %: volcado gzip
EXPORT_PREPARE_PCT_MAX = 8
EXPORT_ROW_PCT_MAX = 94


def _export_row_progress_pct(written: int, total: int) -> int:
    if total <= 0:
        return EXPORT_PREPARE_PCT_MAX
    span = EXPORT_ROW_PCT_MAX - EXPORT_PREPARE_PCT_MAX
    return EXPORT_PREPARE_PCT_MAX + int((written / total) * span)


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


@dataclass(frozen=True)
class _KardexQuery:
    sql: str
    params: tuple[Any, ...]
    count_sql: str


def _build_kardex_query(
    col_cache: TableColumnCache,
    cur: Any,
    *,
    mode: str,
    codigo: str | None,
    since_watermark: TransactionWatermark | None,
    adjustments_only: bool,
) -> _KardexQuery:
    where_parts: list[str] = []
    params: list[Any] = []

    if adjustments_only:
        where_parts.extend(
            [
                "IFNULL(compras, 0) = 0",
                "IFNULL(ventas, 0) = 0",
                (
                    "(IFNULL(ajustesp, 0) <> 0 OR IFNULL(ajustesn, 0) <> 0 "
                    "OR IFNULL(devoc, 0) <> 0 OR IFNULL(devov, 0) <> 0)"
                ),
            ]
        )
        select = """
            SELECT indice_placeholder AS indice, contador, numero, codigo, fecha,
                   compras, ventas, ajustesp, ajustesn, devoc, devov, costo, kobs
        """
    elif mode == "purchase":
        where_parts.append("IFNULL(compras, 0) <> 0")
        select = """
            SELECT indice_placeholder AS indice, contador, numero, codigo, fecha, costo,
                   compras, ventas, cajero, kobs
        """
    else:
        ventas_where, ventas_params = build_kardex_ventas_where(
            col_cache,
            cur,
            codigo=codigo,
            since_watermark=since_watermark,
        )
        where_parts.extend(ventas_where)
        params.extend(ventas_params)
        select = """
            SELECT indice_placeholder AS indice, contador, numero, codigo, fecha, costo,
                   compras, ventas, cajero, kobs
        """

    kardex_cols = col_cache.columns(cur, "kardex")
    has_fecha = "fecha" in kardex_cols
    has_indice = "indice" in kardex_cols
    has_contador = "contador" in kardex_cols

    if mode != "sale":
        if codigo:
            where_parts.append("TRIM(codigo) = %s")
            params.append(codigo.strip())
        apply_kardex_watermark_filter(
            where_parts,
            params,
            since_watermark,
            table_alias=None,
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

    select = select.replace("indice_placeholder", indice_select)
    where = " AND ".join(where_parts)
    count_sql = f"SELECT COUNT(*) AS c FROM kardex WHERE {where}"
    sql = f"""
        {select}
        FROM kardex
        WHERE {where}
        ORDER BY {order_by}
    """
    return _KardexQuery(sql=sql, params=tuple(params), count_sql=count_sql)


def _count_kardex_query(cur: Any, query: _KardexQuery) -> int:
    cur.execute(query.count_sql, query.params)
    row = cur.fetchone()
    if not row:
        return 0
    return int(row.get("c") or 0)


def _stream_kardex_batches(
    cur: Any,
    query: _KardexQuery,
    *,
    batch_size: int = KARDEX_FETCH_BATCH,
) -> Iterator[list[dict[str, Any]]]:
    cur.execute(query.sql, query.params)
    while True:
        batch = cur.fetchmany(batch_size)
        if not batch:
            break
        yield list(batch)


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
        "contador": row.get("contador"),
        "ccaja": str(row.get("cajero") or "").strip(),
        "fecha": row.get("fecha"),
        "cantidad": ventas,
        "kardex_indice": row.get("indice"),
    }


def _track_codigo(codigos_seen: set[str], row: dict[str, Any]) -> None:
    c = str(row.get("codigo") or "").strip()
    if c:
        codigos_seen.add(c)


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

    Lee kardex por lotes (fetchmany) y enriquece con índices en memoria (scom / diariovi).
    """
    if mode not in {"purchase", "sale"}:
        raise RuntimeError("mode must be purchase|sale")

    path = _job_file(job_id)
    tmp = Path(f"{path}.tmp")
    codigos_seen: set[str] = set()
    max_watermark: TransactionWatermark | None = None
    written = 0

    with ExportTransactionEnricher(mysql, bulk_file_export=True) as enricher:
        col_cache = enricher.col_cache
        cur = enricher._cur
        if cur is None:
            raise RuntimeError("export enricher sin cursor MySQL")

        main_query = _build_kardex_query(
            col_cache,
            cur,
            mode=mode,
            codigo=codigo,
            since_watermark=since_watermark,
            adjustments_only=False,
        )
        adj_query = _build_kardex_query(
            col_cache,
            cur,
            mode=mode,
            codigo=codigo,
            since_watermark=since_watermark,
            adjustments_only=True,
        )
        kardex_count = _count_kardex_query(cur, main_query)
        adj_count = _count_kardex_query(cur, adj_query)
        total = kardex_count + adj_count

        if mode == "purchase" and kardex_count > 0:
            scom_n = enricher.warm_purchase_scom_index(codigo_filter=codigo)
            trace(
                "sync.export.warm_purchase_scom_index",
                job_id=job_id,
                scom_rows=scom_n,
                kardex_rows=kardex_count,
            )
        elif mode == "sale" and kardex_count > 0:
            prepare_pct_holder = [0]

            def _on_prepare_pct(pct: int) -> None:
                prepare_pct_holder[0] = pct
                if on_progress and total > 0:
                    on_progress(0, total, pct)

            d_n = enricher.warm_sale_diariovi_index(
                codigo_filter=codigo,
                since_watermark=since_watermark,
                kardex_rows=kardex_count,
                on_prepare_pct=_on_prepare_pct if on_progress else None,
            )
            trace(
                "sync.export.warm_sale_diariovi_index",
                job_id=job_id,
                diariovi_rows=d_n,
                kardex_rows=kardex_count,
                prepare_pct=prepare_pct_holder[0],
            )

        if on_progress and total >= 0:
            start_pct = EXPORT_PREPARE_PCT_MAX if mode == "sale" and kardex_count > 0 else 0
            on_progress(0, total, start_pct)

        progress_stride = max(total // 100, 1) if total > 0 else 1
        progress_every = min(250, progress_stride) if total > 0 else 1

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
                    mode: None,
                },
            }
            gz.write(json.dumps(manifest, ensure_ascii=True) + "\n")

            for batch in _stream_kardex_batches(cur, main_query):
                if should_cancel:
                    should_cancel()
                max_watermark = merge_watermark(max_watermark, batch)
                for row in batch:
                    _track_codigo(codigos_seen, row)
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
                        or written % progress_every == 0
                        or written % progress_stride == 0
                    ):
                        pct = _export_row_progress_pct(written, total)
                        on_progress(written, total, pct)

            for batch in _stream_kardex_batches(cur, adj_query):
                if should_cancel:
                    should_cancel()
                max_watermark = merge_watermark(max_watermark, batch)
                for row in batch:
                    _track_codigo(codigos_seen, row)
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
                    if on_progress and total > 0 and (
                        written == total
                        or written % progress_every == 0
                        or written % progress_stride == 0
                    ):
                        pct = _export_row_progress_pct(written, total)
                        on_progress(written, total, pct)

            snapshot_rows = append_stock_snapshot_lines(
                gz,
                mysql=mysql,
                cur=cur,
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
