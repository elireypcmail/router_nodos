from __future__ import annotations

import anyio
import httpx

from categoria_trace import trace, trace_exc, trace_warn
from config import settings
from json_util import json_safe
from node_catalog import load_node_catalog


def _num_field(row: dict, key: str) -> float:
    raw = row.get(key)
    if raw is None:
        return 0.0
    if isinstance(raw, (int, float)):
        return float(raw)
    try:
        return float(str(raw).strip())
    except (TypeError, ValueError):
        return 0.0


def _ingest_codigo(payload: dict) -> str:
    raw = payload.get("codigo")
    if raw is None:
        return "—"
    return str(raw).strip() or "—"


_INGEST_LABEL = {
    "purchase": "compra",
    "sale": "venta",
    "kardex": "kardex",
    "inventory_lot": "lote",
}


def _is_kardex_inventory_adjustment(row: dict) -> bool:
    """Ajustes y devoluciones vía kardex; ignorar filas espejo de compras/ventas."""
    if _num_field(row, "compras") != 0 or _num_field(row, "ventas") != 0:
        return False
    return (
        _num_field(row, "ajustesp") != 0
        or _num_field(row, "ajustesn") != 0
        or _num_field(row, "devoc") != 0
        or _num_field(row, "devov") != 0
    )


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

        # Contrato actual del hub:
        # POST /api/nodo/events/batch { "events": [ {event_id, entity_type, payload, occurred_at?}, ... ] }
        # Nota: el hub valida el nodo por Bearer token.
        if settings.nodo_api_token:
            headers["Authorization"] = f"Bearer {settings.nodo_api_token}"

        async with httpx.AsyncClient(timeout=30.0) as client:
            events: list[dict] = []
            for e in batch:
                table = str(e.get("table") or "").strip().lower()

                outbox_id = e.get("outbox_id")
                if outbox_id is None:
                    continue

                pk = e.get("pk") or {}
                row = e.get("row") or {}
                payload = {**pk, **row}

                entity_type: str | None = None
                if table == "comprasdbf":
                    entity_type = "purchase"
                elif table == "ventasi":
                    entity_type = "sale"
                elif table in {"kardex", "kardexd"}:
                    if not _is_kardex_inventory_adjustment(payload):
                        continue
                    entity_type = "kardex"
                    op = str(e.get("op") or "I").strip().upper()
                    if op:
                        payload["outbox_op"] = op
                elif table == "detalle":
                    entity_type = "inventory_lot"
                    op = str(e.get("op") or "I").strip().upper()
                    if op:
                        payload["outbox_op"] = op
                if not entity_type:
                    continue

                codigo = _ingest_codigo(payload)
                if codigo != "—":
                    try:
                        catalog = await anyio.to_thread.run_sync(
                            load_node_catalog, codigo
                        )
                        if catalog:
                            payload["node_catalog"] = catalog
                    except Exception as exc:
                        trace_warn(
                            "hub.ingest.node_catalog_skip",
                            codigo=codigo,
                            error=str(exc),
                        )

                label = _INGEST_LABEL.get(entity_type, entity_type)
                print(
                    f"[hub-ingest] → enviar {label} "
                    f"outbox_id={outbox_id} codigo={_ingest_codigo(payload)} "
                    f"tabla={table}",
                    flush=True,
                )

                events.append(
                    {
                        "event_id": str(outbox_id),
                        "entity_type": entity_type,
                        "payload": payload,
                        "occurred_at": e.get("created_at"),
                    }
                )

            if not events:
                return

            print(
                f"[hub-ingest] POST {url} ({len(events)} evento(s) transaccional)",
                flush=True,
            )
            resp = await client.post(url, json={"events": events}, headers=headers)
            resp.raise_for_status()
            print(f"[hub-ingest] OK hub respondió {resp.status_code}", flush=True)

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

    async def fetch_proveedores_page(self, page: int, limit: int) -> dict:
        url = f"{self._base}{settings.hub_nodo_sync_proveedores_path}"
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
            raise RuntimeError("Respuesta inesperada del hub al paginar proveedores")

    async def fetch_productos_page(self, page: int, limit: int) -> dict:
        url = f"{self._base}{settings.hub_nodo_sync_productos_path}"
        headers = {"Authorization": f"Bearer {settings.nodo_api_token}"}
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.get(
                url,
                params={"page": int(page), "limit": int(limit)},
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, dict):
                return data
            raise RuntimeError("Respuesta inesperada del hub al paginar productos")

    async def report_catalog_pull_warnings(self, items: list[dict]) -> int:
        if not items:
            return 0
        url = f"{self._base}{settings.hub_nodo_catalog_pull_warnings_path}"
        headers = {
            "Authorization": f"Bearer {settings.nodo_api_token}",
            "Content-Type": "application/json",
        }
        reported = 0
        chunk_size = 100
        async with httpx.AsyncClient(timeout=120.0) as client:
            for i in range(0, len(items), chunk_size):
                chunk = items[i : i + chunk_size]
                resp = await client.post(
                    url,
                    json=json_safe({"items": chunk}),
                    headers=headers,
                )
                resp.raise_for_status()
                data = resp.json()
                if isinstance(data, dict):
                    reported += int(data.get("reported") or len(chunk))
                else:
                    reported += len(chunk)
        return reported

    async def push_categories_batch(self, items: list[dict]) -> dict:
        return await self._push_batch(settings.hub_nodo_catalog_push_categorias_path, items)

    async def push_providers_batch(self, items: list[dict]) -> dict:
        return await self._push_batch(settings.hub_nodo_catalog_push_proveedores_path, items)

    async def push_inventory_batch(self, items: list[dict]) -> dict:
        return await self._push_batch(settings.hub_nodo_catalog_push_inventario_path, items)

    async def _push_batch(self, path: str, items: list[dict]) -> dict:
        if not items:
            return {
                "inserted": 0,
                "unchanged": 0,
                "conflicts": 0,
                "missing_dependencies": 0,
                "skipped": 0,
                "warnings_reported": 0,
            }
        url = f"{self._base}{path}"
        headers = {
            "Authorization": f"Bearer {settings.nodo_api_token}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                url,
                json=json_safe({"items": items}),
                headers=headers,
            )
            if resp.status_code >= 400:
                detail = resp.text[:500]
                try:
                    body = resp.json()
                    if isinstance(body, dict):
                        msg = body.get("message")
                        if isinstance(msg, list):
                            detail = "; ".join(str(m) for m in msg)
                        elif isinstance(msg, str):
                            detail = msg
                except Exception:
                    pass
                raise RuntimeError(
                    f"Hub push batch HTTP {resp.status_code}: {detail}"
                ) from None
            data = resp.json()
            if isinstance(data, dict):
                return data
            raise RuntimeError("Respuesta inesperada del hub en push batch")
