from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from db_mysql import MySqlClient


@dataclass(frozen=True)
class OutboxEvent:
    id: int
    table_name: str
    op: str
    pk: dict[str, Any]
    row: dict[str, Any] | None
    created_at: str


class OutboxRepository:
    def __init__(self, mysql: MySqlClient, table_name: str = "sync_outbox"):
        self._mysql = mysql
        self._table = table_name

    def is_configured(self) -> bool:
        return self._mysql.is_configured()

    def ensure_schema(self) -> None:
        conn = self._mysql.connect()
        try:
            cur = conn.cursor()
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self._table} (
                    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
                    table_name VARCHAR(64) NOT NULL,
                    op CHAR(1) NOT NULL,
                    pk_json TEXT NOT NULL,
                    row_json MEDIUMTEXT NULL,
                    created_at DATETIME(3) NOT NULL,
                    status VARCHAR(16) NOT NULL DEFAULT 'pending',
                    attempts INT NOT NULL DEFAULT 0,
                    last_error TEXT NULL,
                    sent_at DATETIME(3) NULL,
                    PRIMARY KEY (id),
                    KEY idx_status_id (status, id),
                    KEY idx_table_created (table_name, created_at)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8;
                """
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def release_to_pending(self, ids: list[int], error: str) -> None:
        """Devuelve eventos a pending (para reintento) e incrementa attempts."""
        if not ids:
            return
        conn = self._mysql.connect()
        try:
            cur = conn.cursor()
            placeholders = ",".join(["%s"] * len(ids))
            cur.execute(
                f"""
                UPDATE {self._table}
                SET status='pending', attempts=attempts+1, last_error=%s
                WHERE id IN ({placeholders})
                """,
                (error[:2000], *ids),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def fetch_pending(self, limit: int = 200) -> list[OutboxEvent]:
        conn = self._mysql.connect()
        try:
            cur = conn.cursor(dictionary=True)
            cur.execute(
                f"""
                SELECT id, table_name, op, pk_json, row_json, created_at
                FROM {self._table}
                WHERE status = 'pending'
                ORDER BY id ASC
                LIMIT %s
                """,
                (limit,),
            )
            rows = cur.fetchall() or []
            events: list[OutboxEvent] = []
            for r in rows:
                events.append(
                    OutboxEvent(
                        id=int(r["id"]),
                        table_name=str(r["table_name"]),
                        op=str(r["op"]),
                        pk=json.loads(r["pk_json"]),
                        row=json.loads(r["row_json"]) if r.get("row_json") else None,
                        created_at=self._to_iso(r["created_at"]),
                    )
                )
            return events
        finally:
            conn.close()

    def reserve_pending(self, limit: int = 200) -> list[OutboxEvent]:
        """Reserva eventos para envío marcándolos como processing.

        Esto evita que múltiples workers/consumers envíen el mismo batch.
        """
        conn = self._mysql.connect()
        try:
            conn.start_transaction()
            cur = conn.cursor(dictionary=True)
            cur.execute(
                f"""
                SELECT id, table_name, op, pk_json, row_json, created_at
                FROM {self._table}
                WHERE status = 'pending'
                ORDER BY id ASC
                LIMIT %s
                FOR UPDATE
                """,
                (limit,),
            )
            rows = cur.fetchall() or []
            ids = [int(r["id"]) for r in rows]
            if ids:
                placeholders = ",".join(["%s"] * len(ids))
                cur2 = conn.cursor()
                cur2.execute(
                    f"""
                    UPDATE {self._table}
                    SET status='processing'
                    WHERE id IN ({placeholders}) AND status='pending'
                    """,
                    tuple(ids),
                )

            conn.commit()

            events: list[OutboxEvent] = []
            for r in rows:
                events.append(
                    OutboxEvent(
                        id=int(r["id"]),
                        table_name=str(r["table_name"]),
                        op=str(r["op"]),
                        pk=json.loads(r["pk_json"]),
                        row=json.loads(r["row_json"]) if r.get("row_json") else None,
                        created_at=self._to_iso(r["created_at"]),
                    )
                )
            return events
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def mark_sent(self, ids: list[int]) -> None:
        if not ids:
            return
        conn = self._mysql.connect()
        try:
            cur = conn.cursor()
            placeholders = ",".join(["%s"] * len(ids))
            cur.execute(
                f"""
                UPDATE {self._table}
                SET status='sent', sent_at=NOW(3)
                WHERE id IN ({placeholders})
                """,
                tuple(ids),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def mark_failed(self, ids: list[int], error: str) -> None:
        if not ids:
            return
        conn = self._mysql.connect()
        try:
            cur = conn.cursor()
            placeholders = ",".join(["%s"] * len(ids))
            cur.execute(
                f"""
                UPDATE {self._table}
                SET status='failed', attempts=attempts+1, last_error=%s
                WHERE id IN ({placeholders})
                """,
                (error[:2000], *ids),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def stats(self) -> dict[str, int]:
        conn = self._mysql.connect()
        try:
            cur = conn.cursor(dictionary=True)
            cur.execute(
                f"""
                SELECT status, COUNT(*) as c
                FROM {self._table}
                GROUP BY status
                """
            )
            rows = cur.fetchall() or []
            counts = {str(r["status"]): int(r["c"]) for r in rows}
            return {
                "pending": int(counts.get("pending", 0)),
                "sent": int(counts.get("sent", 0)),
                "failed": int(counts.get("failed", 0)),
            }
        finally:
            conn.close()

    def recent(self, status: str, limit: int = 20) -> list[dict[str, Any]]:
        conn = self._mysql.connect()
        try:
            cur = conn.cursor(dictionary=True)
            cur.execute(
                f"""
                SELECT id, table_name, op, pk_json, created_at, attempts, last_error
                FROM {self._table}
                WHERE status = %s
                ORDER BY id DESC
                LIMIT %s
                """,
                (status, limit),
            )
            rows = cur.fetchall() or []
            out: list[dict[str, Any]] = []
            for r in rows:
                out.append(
                    {
                        "id": int(r["id"]),
                        "table": str(r["table_name"]),
                        "op": str(r["op"]),
                        "pk": json.loads(r["pk_json"]),
                        "created_at": self._to_iso(r["created_at"]),
                        "attempts": int(r.get("attempts") or 0),
                        "last_error": r.get("last_error"),
                    }
                )
            return out
        finally:
            conn.close()

    def _to_iso(self, dt: Any) -> str:
        if isinstance(dt, datetime):
            return dt.replace(tzinfo=timezone.utc).isoformat()
        return str(dt)
