from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Any, Callable

from catalog.push.categoria import fetch_all_categorias
from catalog.push.proveedor import fetch_all_proveedores
from core.json_util import json_safe
from db.mysql import MySqlClient


def _write_manifest_gz(
    tmp: Path,
    *,
    manifest: dict[str, Any],
    rows: list[dict[str, Any]],
    on_progress: Callable[[int, int, int], None] | None = None,
    should_cancel: Callable[[], None] | None = None,
) -> int:
    total = len(rows)
    written = 0
    with gzip.open(tmp, "wt", encoding="utf-8") as gz:
        gz.write(json.dumps(manifest, ensure_ascii=True) + "\n")
        for row in rows:
            if should_cancel:
                should_cancel()
            gz.write(json.dumps(row, ensure_ascii=True) + "\n")
            written += 1
            if on_progress and total > 0:
                pct = int((written / total) * 50)
                on_progress(written, total, pct)
    return written if total > 0 else written


def export_category_push_file(
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
    items = fetch_all_categorias(mysql)
    manifest = {
        "v": 1,
        "direction": "push",
        "entity": "inventory_category",
        "nodoId": nodo_id,
        "totalRows": len(items),
        "schema": "inventory_category_v1",
    }
    total = _write_manifest_gz(
        tmp,
        manifest=manifest,
        rows=items,
        on_progress=on_progress,
        should_cancel=should_cancel,
    )
    tmp.replace(path)
    return path, total if total > 0 else len(items)


def export_provider_push_file(
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
    items = fetch_all_proveedores(mysql)
    manifest = {
        "v": 1,
        "direction": "push",
        "entity": "provider",
        "nodoId": nodo_id,
        "totalRows": len(items),
        "schema": "provider_v1",
    }
    total = _write_manifest_gz(
        tmp,
        manifest=manifest,
        rows=items,
        on_progress=on_progress,
        should_cancel=should_cancel,
    )
    tmp.replace(path)
    return path, total if total > 0 else len(items)
