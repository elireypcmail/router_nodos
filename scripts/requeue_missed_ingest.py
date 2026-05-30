#!/usr/bin/env python3
"""Reencola filas sync_outbox marcadas sent pero no presentes en nodo_ingested_events del hub.

Uso (desde Multishop-nodo-API con venv y .env):
  python scripts/requeue_missed_ingest.py --dry-run
  python scripts/requeue_missed_ingest.py --apply

Requiere acceso a MySQL local (sync_outbox) y Postgres del hub (nodo_ingested_events).
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.config import settings  # noqa: E402
from db.mysql import MySqlClient  # noqa: E402

INGEST_TABLES = ("comprasdbf", "ventasi", "kardex", "kardexd", "detalle")


def _hub_event_ids(nodo_id: str) -> set[str]:
    pg_host = os.environ.get("HUB_PG_HOST", "127.0.0.1")
    pg_port = os.environ.get("HUB_PG_PORT", "5432")
    pg_user = os.environ.get("HUB_PG_USER", "multishop")
    pg_pass = os.environ.get("HUB_PG_PASSWORD", "multishop")
    pg_db = os.environ.get("HUB_PG_DB", "multishop_hub")

    sql = (
        "SELECT event_id FROM nodo_ingested_events "
        f"WHERE nodo_id = '{nodo_id}';"
    )
    cmd = [
        "docker",
        "exec",
        os.environ.get("HUB_PG_CONTAINER", "multishop-postgres-hub-dev"),
        "psql",
        "-U",
        pg_user,
        "-d",
        pg_db,
        "-t",
        "-A",
        "-c",
        sql,
    ]
    try:
        out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True)
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"Postgres query failed: {exc.output}") from exc
    return {line.strip() for line in out.splitlines() if line.strip()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actualiza sync_outbox a pending (por defecto solo lista)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Alias explícito de modo lectura (default)",
    )
    args = parser.parse_args()
    apply = args.apply and not args.dry_run

    mysql = MySqlClient()
    if not mysql.is_configured():
        print("MYSQL_* no configurado", file=sys.stderr)
        return 1

    nodo_id = settings.nodo_id.strip()
    if not nodo_id:
        print("NODO_ID vacío en .env", file=sys.stderr)
        return 1

    hub_ids = _hub_event_ids(nodo_id)
    conn = mysql.connect()
    try:
        cur = conn.cursor(dictionary=True)
        placeholders = ",".join(["%s"] * len(INGEST_TABLES))
        cur.execute(
            f"""
            SELECT id, table_name, status
            FROM sync_outbox
            WHERE table_name IN ({placeholders})
              AND status = 'sent'
            ORDER BY id ASC
            """,
            INGEST_TABLES,
        )
        rows = cur.fetchall() or []
        missing = [r for r in rows if str(r["id"]) not in hub_ids]
        if not missing:
            print(f"OK: no hay eventos transaccionales sent sin ingest en hub (nodo={nodo_id})")
            return 0

        print(f"Eventos sent sin confirmar en hub ({len(missing)}):")
        for r in missing:
            print(f"  id={r['id']} table={r['table_name']}")

        if not apply:
            print("\nDry-run. Usa --apply para reencolar a pending.")
            return 0

        ids = [int(r["id"]) for r in missing]
        ph = ",".join(["%s"] * len(ids))
        cur.execute(
            f"""
            UPDATE sync_outbox
            SET status='pending', sent_at=NULL, last_error='requeue: missing hub ingest'
            WHERE id IN ({ph})
            """,
            tuple(ids),
        )
        conn.commit()
        print(f"Reencolados {len(ids)} evento(s) a pending.")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
