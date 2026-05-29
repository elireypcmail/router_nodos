from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from db_mysql import MySqlClient
from json_util import loads_outbox_json


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

    def recover_processing(self) -> int:
        """Return rows stuck in processing to pending (consumer died mid-batch)."""
        conn = self._mysql.connect()
        try:
            cur = conn.cursor()
            cur.execute(
                f"""
                UPDATE {self._table}
                SET status='pending',
                    attempts=attempts + 1,
                    last_error=LEFT(
                        CONCAT('recovered processing: ', COALESCE(last_error, '')),
                        2000
                    )
                WHERE status = 'processing'
                """
            )
            conn.commit()
            return int(cur.rowcount or 0)
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def release_to_pending(self, ids: list[int], error: str) -> None:
        """Return events to pending (for retry) and increment attempts."""
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
                oid = int(r["id"])
                events.append(
                    OutboxEvent(
                        id=oid,
                        table_name=str(r["table_name"]),
                        op=str(r["op"]),
                        pk=loads_outbox_json(
                            r["pk_json"], context=f"outbox_id={oid} pk_json"
                        ),
                        row=(
                            loads_outbox_json(
                                r["row_json"],
                                context=f"outbox_id={oid} row_json",
                            )
                            if r.get("row_json")
                            else None
                        ),
                        created_at=self._to_iso(r["created_at"]),
                    )
                )
            return events
        finally:
            conn.close()

    def reserve_pending(self, limit: int = 200) -> list[OutboxEvent]:
        """Reserve events for send by marking them processing.

        Prevents multiple workers/consumers from sending the same batch.
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
                oid = int(r["id"])
                events.append(
                    OutboxEvent(
                        id=oid,
                        table_name=str(r["table_name"]),
                        op=str(r["op"]),
                        pk=loads_outbox_json(
                            r["pk_json"], context=f"outbox_id={oid} pk_json"
                        ),
                        row=(
                            loads_outbox_json(
                                r["row_json"],
                                context=f"outbox_id={oid} row_json",
                            )
                            if r.get("row_json")
                            else None
                        ),
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
                SET status='sent', sent_at=NOW(3), last_error=NULL
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

    def mark_ignored(self, ids: list[int]) -> None:
        """Non-transactional rows (sinv/catego/kardex mirror) - not sent to ingest."""
        if not ids:
            return
        conn = self._mysql.connect()
        try:
            cur = conn.cursor()
            placeholders = ",".join(["%s"] * len(ids))
            cur.execute(
                f"""
                UPDATE {self._table}
                SET status='ignored', sent_at=NOW(3), last_error=NULL
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

    def apply_send_result(self, result) -> None:
        from outbox_send_result import OutboxSendResult

        if not isinstance(result, OutboxSendResult):
            raise TypeError("result must be OutboxSendResult")

        if result.sent_ids:
            self.mark_sent(result.sent_ids)
        if result.ignored_ids:
            self.mark_ignored(result.ignored_ids)
        if result.failed_ids:
            sample = next(iter(result.hub_failed_messages.values()), "hub ingest failed")
            self.release_to_pending(result.failed_ids, sample)

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

    _QUEUE_STATUSES = frozenset({"pending", "processing", "failed"})

    def list_queue(
        self,
        *,
        statuses: list[str] | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        """List outbox rows for admin (non-sent by default)."""
        allowed = list(statuses) if statuses else ["pending", "processing", "failed"]
        normalized = [
            s.strip().lower()
            for s in allowed
            if s and s.strip().lower() in self._QUEUE_STATUSES
        ]
        if not normalized:
            normalized = ["pending", "processing", "failed"]
        placeholders = ",".join(["%s"] * len(normalized))
        conn = self._mysql.connect()
        try:
            cur = conn.cursor(dictionary=True)
            cur.execute(
                f"""
                SELECT COUNT(*) AS c
                FROM {self._table}
                WHERE status IN ({placeholders})
                """,
                tuple(normalized),
            )
            total_row = cur.fetchone() or {}
            total = int(total_row.get("c") or 0)

            cur.execute(
                f"""
                SELECT id, table_name, op, pk_json, status, attempts,
                       last_error, created_at, sent_at
                FROM {self._table}
                WHERE status IN ({placeholders})
                ORDER BY id ASC
                LIMIT %s OFFSET %s
                """,
                (*normalized, limit, offset),
            )
            rows = cur.fetchall() or []
            items: list[dict[str, Any]] = []
            for r in rows:
                items.append(
                    {
                        "id": int(r["id"]),
                        "table": str(r["table_name"]),
                        "op": str(r["op"]),
                        "pk": loads_outbox_json(
                            r["pk_json"],
                            context=f"outbox_id={int(r['id'])} pk_json",
                        ),
                        "status": str(r["status"]),
                        "attempts": int(r.get("attempts") or 0),
                        "last_error": r.get("last_error"),
                        "created_at": self._to_iso(r["created_at"]),
                        "sent_at": self._to_iso(r["sent_at"])
                        if r.get("sent_at")
                        else None,
                    }
                )
            return items, total
        finally:
            conn.close()

    def delete_by_ids(self, ids: list[int]) -> int:
        """Remove queue rows (pending/processing/failed only)."""
        if not ids:
            return 0
        conn = self._mysql.connect()
        try:
            cur = conn.cursor()
            placeholders = ",".join(["%s"] * len(ids))
            cur.execute(
                f"""
                DELETE FROM {self._table}
                WHERE id IN ({placeholders})
                  AND status IN ('pending', 'processing', 'failed')
                """,
                tuple(ids),
            )
            conn.commit()
            return int(cur.rowcount or 0)
        except Exception:
            conn.rollback()
            raise
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
                        "pk": loads_outbox_json(
                            r["pk_json"],
                            context=f"outbox_id={int(r['id'])} pk_json",
                        ),
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
