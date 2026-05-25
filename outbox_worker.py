from __future__ import annotations

import asyncio
from typing import Any

from hub_client import HubClient
from outbox_mysql import OutboxRepository


class OutboxWorker:
    def __init__(
        self,
        repo: OutboxRepository,
        hub: HubClient,
        interval_seconds: float = 1.0,
        batch_size: int = 200,
    ):
        self._repo = repo
        self._hub = hub
        self._interval = interval_seconds
        self._batch = batch_size
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()

    def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            await asyncio.wait([self._task], timeout=5)

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                events = self._repo.fetch_pending(limit=self._batch)
                if not events:
                    await asyncio.sleep(self._interval)
                    continue

                payload: list[dict[str, Any]] = []
                ids: list[int] = []
                for e in events:
                    payload.append(
                        {
                            "outbox_id": e.id,
                            "table": e.table_name,
                            "op": e.op,
                            "pk": e.pk,
                            "row": e.row,
                            "created_at": e.created_at,
                        }
                    )
                    ids.append(e.id)

                await self._hub.send_outbox_batch(payload)
                self._repo.mark_sent(ids)
            except Exception as ex:
                try:
                    if "ids" in locals():
                        self._repo.mark_failed(ids, str(ex))
                finally:
                    await asyncio.sleep(self._interval)
