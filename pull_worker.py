from __future__ import annotations

import asyncio
from typing import Any

from hub_client import HubClient
from sync_models import SyncApplyRequest
from sync_store import SyncEvent, SyncStore


class HubPullWorker:
    def __init__(
        self,
        store: SyncStore,
        hub: HubClient,
        interval_seconds: float = 10.0,
        batch_size: int = 200,
    ):
        self._store = store
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
                state = await self._store.get_state()
                last_seq = int(state.get("last_applied_sequence") or 0)
                from_seq = last_seq + 1

                events = await self._hub.fetch_sync_events(from_seq=from_seq, limit=self._batch)
                if events:
                    for e in events:
                        body = SyncApplyRequest.model_validate(e)
                        await self._store.enqueue(
                            SyncEvent(
                                event_id=body.event_id,
                                entity=body.entity,
                                action=body.action,
                                payload=body.payload,
                                sequence=body.sequence,
                                created_at=body.created_at,
                            )
                        )
                    await asyncio.sleep(0)
                else:
                    await asyncio.sleep(self._interval)
            except Exception:
                await asyncio.sleep(self._interval)


async def pull_all_categories(hub: HubClient, page_size: int = 100) -> list[dict[str, Any]]:
    from categoria_trace import trace, trace_exc

    trace("pull_all_categories.start", page_size=page_size)
    all_items: list[dict[str, Any]] = []
    page = 1
    try:
        while True:
            trace("pull_all_categories.page", page=page)
            data = await hub.fetch_categorias_page(page=page, limit=page_size)
            items = data.get("items") or []
            if not isinstance(items, list):
                raise RuntimeError("items inválido en respuesta de categorías")
            all_items.extend(items)
            has_more = data.get("hasMore")
            trace(
                "pull_all_categories.page.done",
                page=page,
                page_items=len(items),
                total=len(all_items),
                has_more=has_more,
            )
            if not has_more:
                break
            page += 1
        trace("pull_all_categories.done", pages=page, total=len(all_items))
        return all_items
    except Exception as exc:
        trace_exc("pull_all_categories.failed", exc, page=page, total=len(all_items))
        raise


async def _pull_all_pages(
    hub: HubClient,
    fetch_page,
    page_size: int,
    trace_prefix: str,
) -> list[dict[str, Any]]:
    from categoria_trace import trace, trace_exc

    trace(f"{trace_prefix}.start", page_size=page_size)
    all_items: list[dict[str, Any]] = []
    page = 1
    try:
        while True:
            trace(f"{trace_prefix}.page", page=page)
            data = await fetch_page(page=page, limit=page_size)
            items = data.get("items") or []
            if not isinstance(items, list):
                raise RuntimeError("items inválido en respuesta del hub")
            all_items.extend(items)
            if not data.get("hasMore"):
                break
            page += 1
        trace(f"{trace_prefix}.done", pages=page, total=len(all_items))
        return all_items
    except Exception as exc:
        trace_exc(f"{trace_prefix}.failed", exc, page=page, total=len(all_items))
        raise


async def pull_all_providers(hub: HubClient, page_size: int = 100) -> list[dict[str, Any]]:
    return await _pull_all_pages(
        hub,
        hub.fetch_proveedores_page,
        page_size,
        "pull_all_providers",
    )


async def pull_all_products(hub: HubClient, page_size: int = 100) -> list[dict[str, Any]]:
    return await _pull_all_pages(
        hub,
        hub.fetch_productos_page,
        page_size,
        "pull_all_products",
    )
