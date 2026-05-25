from __future__ import annotations

import httpx

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

    async def create_categoria_in_hub(self, payload: dict) -> dict:
        url = f"{self._base}{settings.hub_nodo_categorias_path}"
        headers = {"Authorization": f"Bearer {settings.nodo_api_token}"}
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, dict):
                return data
            raise RuntimeError("Respuesta inesperada del hub al crear categoria")

    async def fetch_categorias_page(self, page: int, limit: int) -> dict:
        url = f"{self._base}{settings.hub_nodo_sync_categorias_path}"
        headers = {"Authorization": f"Bearer {settings.nodo_api_token}"}
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.get(
                url,
                params={"page": int(page), "limit": int(limit)},
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, dict):
                return data
            raise RuntimeError("Respuesta inesperada del hub al paginar categorias")
