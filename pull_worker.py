from __future__ import annotations

from typing import Any

from hub_client import HubClient


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
                raise RuntimeError("invalid items in categories hub response")
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
                raise RuntimeError("invalid items in hub response")
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
