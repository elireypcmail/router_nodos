import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import aiosqlite


@dataclass(frozen=True)
class SyncEvent:
    event_id: str
    entity: str
    action: str
    payload: dict[str, Any]
    sequence: int
    created_at: str


class SyncStore:
    def __init__(self, db_path: str):
        self.db_path = db_path

    async def init(self) -> None:
        os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("PRAGMA journal_mode=WAL")
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS sync_state (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    last_applied_sequence INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL
                )
                """
            )
            await db.execute(
                """
                INSERT OR IGNORE INTO sync_state (id, last_applied_sequence, updated_at)
                VALUES (1, 0, ?)
                """,
                (self._now(),),
            )
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS sync_queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL UNIQUE,
                    sequence INTEGER NOT NULL,
                    entity TEXT NOT NULL,
                    action TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    enqueued_at TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    attempts INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT
                )
                """
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_sync_queue_status ON sync_queue(status, id)"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_sync_queue_sequence ON sync_queue(sequence)"
            )
            await db.commit()

    async def enqueue(self, event: SyncEvent) -> bool:
        async with aiosqlite.connect(self.db_path) as db:
            try:
                await db.execute(
                    """
                    INSERT INTO sync_queue (
                        event_id, sequence, entity, action, payload_json, created_at, enqueued_at, status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending')
                    """,
                    (
                        event.event_id,
                        event.sequence,
                        event.entity,
                        event.action,
                        json.dumps(event.payload, ensure_ascii=True),
                        event.created_at,
                        self._now(),
                    ),
                )
                await db.commit()
                return True
            except sqlite3.IntegrityError:
                return False

    async def get_state(self) -> dict[str, Any]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT last_applied_sequence, updated_at FROM sync_state WHERE id = 1"
            )
            row = await cur.fetchone()
            cur2 = await db.execute(
                "SELECT status, COUNT(*) as c FROM sync_queue GROUP BY status"
            )
            counts = {r["status"]: r["c"] for r in await cur2.fetchall()}
            return {
                "last_applied_sequence": int(row["last_applied_sequence"]),
                "state_updated_at": row["updated_at"],
                "queue": {
                    "pending": int(counts.get("pending", 0)),
                    "processing": int(counts.get("processing", 0)),
                    "done": int(counts.get("done", 0)),
                    "failed": int(counts.get("failed", 0)),
                },
            }

    async def claim_next(self) -> SyncEvent | None:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            await db.execute("BEGIN IMMEDIATE")
            cur = await db.execute(
                """
                SELECT id, event_id, sequence, entity, action, payload_json, created_at
                FROM sync_queue
                WHERE status = 'pending'
                ORDER BY sequence ASC, id ASC
                LIMIT 1
                """
            )
            row = await cur.fetchone()
            if not row:
                await db.commit()
                return None

            await db.execute(
                "UPDATE sync_queue SET status='processing' WHERE id = ?",
                (row["id"],),
            )
            await db.commit()

            return SyncEvent(
                event_id=row["event_id"],
                entity=row["entity"],
                action=row["action"],
                payload=json.loads(row["payload_json"]),
                sequence=int(row["sequence"]),
                created_at=row["created_at"],
            )

    async def mark_done(self, event_id: str, sequence: int) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE sync_queue SET status='done' WHERE event_id = ?",
                (event_id,),
            )
            await db.execute(
                "UPDATE sync_state SET last_applied_sequence = ?, updated_at = ? WHERE id = 1",
                (sequence, self._now()),
            )
            await db.commit()

    async def mark_failed(self, event_id: str, error: str) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                UPDATE sync_queue
                SET status='failed', attempts=attempts+1, last_error=?
                WHERE event_id = ?
                """,
                (error[:2000], event_id),
            )
            await db.commit()

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()
