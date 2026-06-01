from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Any, Iterator

from core.config import settings
from db.mysql import MySqlClient
from core.json_util import json_safe
from catalog.push.inventario import SINV_PUSH_EXTRA_FIELDS, _fetch_detalle_by_codigo
from db.sinv_store import SINV_HUB_FIELDS


def export_inventory_push_file(
    job_id: str,
    mysql: MySqlClient,
    nodo_id: str,
    *,
    on_progress=None,
    should_cancel=None,
) -> tuple[Path, int]:
    from sync.jobs.files import job_file_path

    path = job_file_path(job_id)
    tmp = Path(f"{path}.tmp")
    detalle_map = _fetch_detalle_by_codigo(mysql)
    sinv_cols = ", ".join([*SINV_HUB_FIELDS, *SINV_PUSH_EXTRA_FIELDS])

    def count_rows() -> int:
        conn = mysql.connect()
        try:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM sinv")
            row = cur.fetchone()
            return int(row[0] if row else 0)
        finally:
            conn.close()

    total = count_rows()
    written = 0

    with gzip.open(tmp, "wt", encoding="utf-8") as gz:
        manifest = {
            "v": 1,
            "direction": "push",
            "entity": "inventory",
            "nodoId": nodo_id,
            "totalRows": total,
            "schema": "inventory_v1",
        }
        gz.write(json.dumps(manifest, ensure_ascii=True) + "\n")

        conn = mysql.connect()
        try:
            cur = conn.cursor(dictionary=True)
            cur.execute(
                f"""
                SELECT {sinv_cols}
                FROM sinv
                ORDER BY codigo ASC
                """
            )
            while True:
                rows = cur.fetchmany(200)
                if not rows:
                    break
                for row in rows:
                    if should_cancel:
                        should_cancel()
                    if not isinstance(row, dict):
                        continue
                    codigo = str(row.get("codigo") or "").strip()
                    if not codigo:
                        continue
                    payload = json_safe(dict(row))
                    payload["lotes"] = detalle_map.get(codigo, [])
                    gz.write(json.dumps(payload, ensure_ascii=True) + "\n")
                    written += 1
                    if on_progress and total > 0:
                        pct = int((written / total) * 50)
                        on_progress(written, total, pct)
        finally:
            conn.close()

    if total == 0:
        total = written
    tmp.replace(path)
    return path, total


def iter_inventory_rows_from_gz(path: Path) -> Iterator[dict[str, Any]]:
    with gzip.open(path, "rt", encoding="utf-8") as gz:
        first = True
        for line in gz:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if first:
                first = False
                continue
            if isinstance(row, dict):
                yield row
