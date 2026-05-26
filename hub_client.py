from __future__ import annotations

import httpx

from categoria_trace import trace, trace_exc, trace_warn
from config import settings


class HubClient:
    def __init__(self):
        if not settings.hub_base_url:
            raise RuntimeError("HUB_BASE_URL no configurado")

        self._base = settings.hub_base_url.rstrip("/")

    async def send_outbox_batch(self, batch: list[dict]) -> None:
        url = f"{self._base}{settings.hub_push_path}"
        headers = {}
        if settings.hub_api_key:
            headers["x-internal-api-key"] = settings.hub_api_key

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, json={"nodo_id": settings.nodo_id, "events": batch}, headers=headers)
            resp.raise_for_status()

    async def fetch_sync_events(self, from_seq: int, limit: int) -> list[dict]:
        url = f"{self._base}{settings.hub_pull_path}"
        headers = {}
        if settings.hub_api_key:
            headers["x-internal-api-key"] = settings.hub_api_key

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                url,
                params={"from": int(from_seq), "limit": int(limit), "nodo_id": settings.nodo_id},
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, dict) and isinstance(data.get("events"), list):
                return list(data["events"])
            if isinstance(data, list):
                return list(data)
            raise RuntimeError("Respuesta inesperada del hub para pull events")

    async def get_categoria_in_hub(self, ccate: str) -> dict | None:
        """None si no existe en el hub (404)."""
        ccate = str(ccate or "").strip()
        url = f"{self._base}{settings.hub_nodo_categorias_path}/{ccate}"
        trace("hub.get_categoria.start", url=url, ccate=ccate)
        headers = {"Authorization": f"Bearer {settings.nodo_api_token}"}
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(url, headers=headers)
                trace("hub.get_categoria.response", ccate=ccate, status=resp.status_code)
                if resp.status_code == 404:
                    trace("hub.get_categoria.not_found", ccate=ccate)
                    return None
                resp.raise_for_status()
                data = resp.json()
                if isinstance(data, dict):
                    trace("hub.get_categoria.found", ccate=ccate)
                    return data
                raise RuntimeError("Respuesta inesperada del hub al consultar categoria")
        except httpx.HTTPStatusError:
            raise
        except Exception as exc:
            trace_exc("hub.get_categoria.failed", exc, url=url, ccate=ccate)
            raise

    async def create_categoria_in_hub(self, payload: dict) -> dict:
        url = f"{self._base}{settings.hub_nodo_categorias_path}"
        ccate = payload.get("ccate")
        trace("hub.create_categoria.start", url=url, ccate=ccate)
        headers = {"Authorization": f"Bearer {settings.nodo_api_token}"}
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(url, json=payload, headers=headers)
                trace("hub.create_categoria.response", ccate=ccate, status=resp.status_code)
                if resp.status_code == 409:
                    trace_warn(
                        "hub.create_categoria.already_exists",
                        ccate=ccate,
                        detail=resp.text[:500] if resp.text else None,
                        hint="Hub sin upsert (reinicia Nest) o categoría ya en Postgres; se considera sincronizado",
                    )
                    return {
                        "ccate": ccate,
                        "message": "already_exists_in_hub",
                        "hub_status": 409,
                    }
                resp.raise_for_status()
                data = resp.json()
                if isinstance(data, dict):
                    trace("hub.create_categoria.done", ccate=ccate)
                    return data
                raise RuntimeError("Respuesta inesperada del hub al crear categoria")
        except Exception as exc:
            trace_exc("hub.create_categoria.failed", exc, url=url, ccate=ccate)
            raise

    async def fetch_categorias_page(self, page: int, limit: int) -> dict:
        url = f"{self._base}{settings.hub_nodo_sync_categorias_path}"
        trace("hub.fetch_categorias_page.start", url=url, page=page, limit=limit)
        headers = {"Authorization": f"Bearer {settings.nodo_api_token}"}
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.get(
                    url,
                    params={"page": int(page), "limit": int(limit)},
                    headers=headers,
                )
                trace("hub.fetch_categorias_page.response", page=page, status=resp.status_code)
                resp.raise_for_status()
                data = resp.json()
                if isinstance(data, dict):
                    items = data.get("items") or []
                    trace(
                        "hub.fetch_categorias_page.done",
                        page=page,
                        items=len(items) if isinstance(items, list) else None,
                        has_more=data.get("hasMore"),
                    )
                    return data
                raise RuntimeError("Respuesta inesperada del hub al paginar categorias")
        except Exception as exc:
            trace_exc("hub.fetch_categorias_page.failed", exc, url=url, page=page)
            raise
