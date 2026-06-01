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


def _iter_kardex_rows(mysql: MySqlClient, *, mode: str, codigo: str | None) -> list[dict[str, Any]]:
    where_parts: list[str] = []
    params: list[Any] = []
    if mode == "purchase":
        where_parts.append("IFNULL(compras, 0) <> 0")
    else:
        where_parts.append("IFNULL(ventas, 0) <> 0")
    if codigo:
        where_parts.append("TRIM(codigo) = %s")
        params.append(codigo.strip())
    where = " AND ".join(where_parts)
    query = f"""
        SELECT indice, contador, numero, codigo, fecha, costo, compras, ventas, cajero, kobs
        FROM kardex
        WHERE {where}
        ORDER BY indice ASC
    """
    conn = mysql.connect()
    try:
        with conn.cursor(dictionary=True) as cur:
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
) -> tuple[Path, int]:
    """
    Crea archivo .ndjson.gz para push transaccional:
    - mode="purchase" -> entity_type purchase
    - mode="sale" -> entity_type sale
    """
    if mode not in {"purchase", "sale"}:
        raise RuntimeError("mode must be purchase|sale")

    path = _job_file(job_id)
    tmp = Path(f"{path}.tmp")
    rows = _iter_kardex_rows(mysql, mode=mode, codigo=codigo)

    with gzip.open(tmp, "wt", encoding="utf-8") as gz:
        manifest = {
            "v": 1,
            "direction": "push",
            "entity": mode,
            "nodoId": nodo_id,
            "totalRows": len(rows),
            "schema": f"{mode}_v1",
            "codigo": (codigo or "").strip() or None,
        }
        gz.write(json.dumps(manifest, ensure_ascii=True) + "\n")

        for row in rows:
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

            event = {
                "entity_type": mode,
                "event_id": f"{mode}-kardex-{row.get('indice')}",
                "payload": json_safe(payload),
                "occurred_at": row.get("fecha"),
            }
            gz.write(json.dumps(event, ensure_ascii=True) + "\n")

    tmp.replace(path)
    return path, len(rows)

