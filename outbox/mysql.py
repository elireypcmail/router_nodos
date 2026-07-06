from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from core.json_util import loads_outbox_json
from core.uuid_v7 import generate_uuid_v7
from db.mysql import MySqlClient

_outbox_schema_ensured = False


@dataclass(frozen=True)
class OutboxEvent:
    id: int
    event_id: str | None
    table_name: str
    op: str
    pk: dict[str, Any]
    row: dict[str, Any] | None
    created_at: str
    attempts: int = 0


OUTBOX_TABLE_NAME = "sync_outbox_router"


class OutboxRepository:
    def __init__(self, mysql: MySqlClient, table_name: str = OUTBOX_TABLE_NAME):
        self._mysql = mysql
        self._table = table_name

    def is_configured(self) -> bool:
        return self._mysql.is_configured()

    def ensure_schema(self) -> None:
        global _outbox_schema_ensured
        if _outbox_schema_ensured:
            return
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
                    event_id CHAR(36) NULL,
                    PRIMARY KEY (id),
                    KEY idx_status_id (status, id),
                    KEY idx_table_created (table_name, created_at),
                    UNIQUE KEY uq_sync_outbox_router_event_id (event_id)
                ) ENGINE=MyISAM DEFAULT CHARSET=utf8;
                """
            )
            conn.commit()
            _outbox_schema_ensured = True
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def recover_processing(self) -> int:
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

    def reserve_pending(self, limit: int = 200) -> list[OutboxEvent]:
        self.ensure_schema()
        conn = self._mysql.connect()
        try:
            conn.start_transaction()
            cur = conn.cursor(dictionary=True)
            cur.execute(
                f"""
                SELECT id, event_id, table_name, op, pk_json, row_json, created_at, attempts
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
                cur2 = conn.cursor()
                for row in rows:
                    if row.get("event_id"):
                        continue
                    new_event_id = generate_uuid_v7()
                    cur2.execute(
                        f"""
                        UPDATE {self._table}
                        SET event_id=%s
                        WHERE id=%s AND event_id IS NULL
                        """,
                        (new_event_id, int(row["id"])),
                    )
                    row["event_id"] = new_event_id
                placeholders = ",".join(["%s"] * len(ids))
                cur2.execute(
                    f"""
                    UPDATE {self._table}
                    SET status='processing'
                    WHERE id IN ({placeholders}) AND status='pending'
                    """,
                    tuple(ids),
                )

            conn.commit()
            return self._rows_to_events(rows)
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
        from outbox.send_result import OutboxSendResult

        if not isinstance(result, OutboxSendResult):
            raise TypeError("result must be OutboxSendResult")

        if result.sent_ids:
            self.mark_sent(result.sent_ids)
        if result.ignored_ids:
            self.mark_ignored(result.ignored_ids)
        if result.failed_ids:
            sample = next(iter(result.failed_messages.values()), "router forward failed")
            self.release_to_pending(result.failed_ids, sample)

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
                "processing": int(counts.get("processing", 0)),
                "sent": int(counts.get("sent", 0)),
                "failed": int(counts.get("failed", 0)),
                "ignored": int(counts.get("ignored", 0)),
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

    def _rows_to_events(self, rows: list[dict[str, Any]]) -> list[OutboxEvent]:
        events: list[OutboxEvent] = []
        for r in rows:
            oid = int(r["id"])
            events.append(
                OutboxEvent(
                    id=oid,
                    event_id=(
                        str(r["event_id"]).strip()
                        if r.get("event_id")
                        else None
                    ),
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
                    attempts=int(r.get("attempts") or 0),
                )
            )
        return events

    def _to_iso(self, dt: Any) -> str:
        if isinstance(dt, datetime):
            return dt.replace(tzinfo=timezone.utc).isoformat()
        return str(dt)
