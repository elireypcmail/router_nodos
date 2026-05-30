import asyncio
from typing import Callable

from core.categoria_trace import is_categoria_entity, trace, trace_exc
from sync.store import SyncEvent, SyncStore


class SyncWorker:
    def __init__(
        self,
        store: SyncStore,
        apply_fn: Callable[[SyncEvent], "asyncio.Future[None]"],
        poll_interval_seconds: float = 0.5,
    ):
        self._store = store
        self._apply_fn = apply_fn
        self._poll = poll_interval_seconds
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
            evt = await self._store.claim_next()
            if not evt:
                await asyncio.sleep(self._poll)
                continue

            categoria = is_categoria_entity(evt.entity)
            if categoria:
                trace(
                    "worker.claimed",
                    event_id=evt.event_id,
                    entity=evt.entity,
                    action=evt.action,
                    sequence=evt.sequence,
                )
            try:
                await self._apply_fn(evt)
                await self._store.mark_done(evt.event_id, evt.sequence)
                if categoria:
                    trace("worker.mark_done", event_id=evt.event_id)
            except Exception as e:
                if categoria:
                    trace_exc("worker.mark_failed", e, event_id=evt.event_id)
                await self._store.mark_failed(evt.event_id, str(e))
                await asyncio.sleep(self._poll)
