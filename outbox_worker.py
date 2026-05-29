from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any

import anyio

from db_mysql import is_transient_mysql_error
from hub_client import HubClient
from log_compat import ascii_safe
from outbox_mysql import OutboxRepository

logger = logging.getLogger("multishop.outbox")


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
            try:
                await asyncio.wait_for(self._task, timeout=5)
            except asyncio.TimeoutError:
                self._task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._task
            except Exception as ex:
                # Evita "Task exception was never retrieved" al apagar.
                logger.debug("Outbox worker stop ignored error: %s", ex)
            finally:
                self._task = None

    async def _run(self) -> None:
        sleep_seconds = self._interval
        while not self._stop.is_set():
            ids: list[int] = []
            try:
                await anyio.to_thread.run_sync(self._repo.recover_processing)
                events = await anyio.to_thread.run_sync(
                    lambda: self._repo.reserve_pending(limit=self._batch),
                )
                if not events:
                    sleep_seconds = self._interval
                    await asyncio.sleep(self._interval)
                    continue

                payload: list[dict[str, Any]] = []
                ids = []
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

                result = await self._hub.send_outbox_batch(payload)
                await anyio.to_thread.run_sync(
                    lambda: self._repo.apply_send_result(result),
                )
                if result.has_failures:
                    logger.warning(
                        "Outbox worker: %s event(s) returned to pending (hub ingest failed)",
                        len(result.failed_ids),
                    )
                sleep_seconds = self._interval
            except asyncio.CancelledError:
                raise
            except Exception as ex:
                if self._stop.is_set():
                    # Durante shutdown no intentamos reencolar ni loggear como fallo operativo.
                    logger.debug("Outbox worker shutdown: %s", ex)
                    break
                logger.warning("Outbox worker: %s", ex)
                if ids:
                    err_msg = ascii_safe(ex)[:2000]
                    try:
                        await anyio.to_thread.run_sync(
                            lambda: self._repo.release_to_pending(ids, err_msg),
                        )
                    except Exception as release_exc:
                        logger.error(
                            "Outbox: could not release %s event(s) back to pending: %s",
                            len(ids),
                            release_exc,
                        )
                if is_transient_mysql_error(ex):
                    sleep_seconds = min(max(sleep_seconds * 2, self._interval), 60.0)
            await asyncio.sleep(sleep_seconds)
