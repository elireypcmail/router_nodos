"""Combina compras + ventas en un solo .ndjson.gz para upload al hub (como inventario)."""

from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Any

from sync.jobs.files import job_file_path


def _count_events_in_gz(path: Path) -> int:
    count = 0
    with gzip.open(path, "rt", encoding="utf-8") as gz:
        first = True
        for line in gz:
            if not line.strip():
                continue
            if first:
                first = False
                continue
            count += 1
    return count


def _copy_events(src: Path, dest_gz) -> None:
    with gzip.open(src, "rt", encoding="utf-8") as gz_in:
        first = True
        for line in gz_in:
            raw = line.strip()
            if not raw:
                continue
            if first:
                first = False
                continue
            dest_gz.write(raw + "\n")


def merge_transaction_push_files(
    job_id: str,
    *,
    purchase_path: Path,
    sale_path: Path,
    purchase_meta: dict[str, Any],
    sale_meta: dict[str, Any],
    nodo_id: str,
) -> Path:
    purchase_rows = int(purchase_meta.get("file_rows") or _count_events_in_gz(purchase_path))
    sale_rows = int(sale_meta.get("file_rows") or _count_events_in_gz(sale_path))
    out = job_file_path(job_id)
    tmp = Path(f"{out}.tmp")

    manifest = {
        "v": 1,
        "direction": "push",
        "entity": "transactions",
        "nodoId": nodo_id,
        "totalRows": purchase_rows + sale_rows,
        "schema": "transactions_v1",
        "purchaseRows": purchase_rows,
        "saleRows": sale_rows,
        "sinceWatermark": {
            "purchase": purchase_meta.get("since_watermark"),
            "sale": sale_meta.get("since_watermark"),
        },
        "maxWatermark": {
            "purchase": purchase_meta.get("max_watermark"),
            "sale": sale_meta.get("max_watermark"),
        },
    }

    with gzip.open(tmp, "wt", encoding="utf-8") as gz_out:
        gz_out.write(json.dumps(manifest, ensure_ascii=True) + "\n")
        _copy_events(purchase_path, gz_out)
        _copy_events(sale_path, gz_out)

    tmp.replace(out)
    return out
