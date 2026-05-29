from __future__ import annotations

import anyio
import httpx
import logging

from categoria_trace import trace, trace_exc, trace_warn
from config import settings
from json_util import json_safe
from node_catalog import load_node_catalog
from outbox_send_result import OutboxSendResult
from sync_http_log import log_sync_error, log_sync_step

logger = logging.getLogger("multishop.outbox")

_MISSING_CODIGO = "-"


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
        return _MISSING_CODIGO
    return str(raw).strip() or _MISSING_CODIGO


_INGEST_LABEL = {
    "purchase": "purchase",
    "sale": "sale",
    "kardex": "kardex",
    "inventory_lot": "lot",
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
            raise RuntimeError("HUB_BASE_URL not set")

        self._base = settings.hub_base_url.rstrip("/")

    async def send_outbox_batch(self, batch: list[dict]) -> OutboxSendResult:
        url = f"{self._base}{settings.hub_push_path}"
        headers: dict[str, str] = {}
        if settings.nodo_api_token:
            headers["Authorization"] = f"Bearer {settings.nodo_api_token}"

        ignored_ids: list[int] = []
        pending_events: list[tuple[int, dict]] = []

        async with httpx.AsyncClient(timeout=30.0) as client:
            for e in batch:
                table = str(e.get("table") or "").strip().lower()

                outbox_id = e.get("outbox_id")
                if outbox_id is None:
                    continue
                outbox_id_int = int(outbox_id)

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
                        ignored_ids.append(outbox_id_int)
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
                    ignored_ids.append(outbox_id_int)
                    continue

                codigo = _ingest_codigo(payload)
                if codigo != _MISSING_CODIGO:
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
                logger.info(
                    "[hub-ingest] -> enviar %s outbox_id=%s codigo=%s tabla=%s",
                    label,
                    outbox_id_int,
                    _ingest_codigo(payload),
                    table,
                )

                pending_events.append(
                    (
                        outbox_id_int,
                        {
                            "event_id": str(outbox_id_int),
                            "entity_type": entity_type,
                            "payload": payload,
                            "occurred_at": e.get("created_at"),
                        },
                    )
                )

            attempted_ids = [oid for oid, _ in pending_events]
            if not pending_events:
                if ignored_ids:
                    logger.debug(
                        "[hub-ingest] batch sin eventos transaccionales (%s ignorados)",
                        len(ignored_ids),
                    )
                return OutboxSendResult(
                    ignored_ids=ignored_ids,
                    attempted_ids=attempted_ids,
                )

            events = [ev for _, ev in pending_events]
            logger.info(
                "[hub-ingest] POST %s (%s evento(s) transaccional)",
                url,
                len(events),
            )
            resp = await client.post(url, json={"events": events}, headers=headers)
            resp.raise_for_status()
            body = resp.json()
            logger.info(
                "[hub-ingest] OK hub responded %s accepted=%s failed=%s",
                resp.status_code,
                body.get("accepted"),
                body.get("failed"),
            )

            sent_ids: list[int] = []
            failed_ids: list[int] = []
            hub_failed_messages: dict[int, str] = {}
            for item in body.get("results") or []:
                if not isinstance(item, dict):
                    continue
                raw_id = item.get("event_id")
                try:
                    oid = int(str(raw_id).strip())
                except (TypeError, ValueError):
                    continue
                status = str(item.get("status") or "").strip().lower()
                if status in {"accepted", "duplicate"}:
                    sent_ids.append(oid)
                    continue
                failed_ids.append(oid)
                message = item.get("message")
                if message:
                    hub_failed_messages[oid] = str(message)

            for oid in attempted_ids:
                if oid in sent_ids or oid in failed_ids:
                    continue
                failed_ids.append(oid)
                hub_failed_messages.setdefault(
                    oid,
                    "hub ingest: evento sin confirmacion en la respuesta",
                )

            if failed_ids:
                logger.warning(
                    "[hub-ingest] %s evento(s) no confirmados por el hub",
                    len(failed_ids),
                )

            return OutboxSendResult(
                sent_ids=sent_ids,
                ignored_ids=ignored_ids,
                failed_ids=failed_ids,
                attempted_ids=attempted_ids,
                hub_failed_messages=hub_failed_messages,
            )

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
                raise RuntimeError("Unexpected hub response when fetching category")
        except httpx.HTTPStatusError:
            raise
        except Exception as exc:
            trace_exc("hub.get_categoria.failed", exc, url=url, ccate=ccate)
            raise

    async def get_proveedor_in_hub(self, cod_prv: str) -> dict | None:
        """None si no existe en el hub (404)."""
        cod_prv = str(cod_prv or "").strip()
        url = f"{self._base}{settings.hub_nodo_proveedores_path}/{cod_prv}"
        headers = {"Authorization": f"Bearer {settings.nodo_api_token}"}
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(url, headers=headers)
                if resp.status_code == 404:
                    return None
                resp.raise_for_status()
                data = resp.json()
                if isinstance(data, dict):
                    return data
                raise RuntimeError("Unexpected hub response when fetching provider")
        except httpx.HTTPStatusError:
            raise
        except Exception as exc:
            trace_exc("hub.get_proveedor.failed", exc, url=url, cod_prv=cod_prv)
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
                        hint="Hub has no upsert (restart Nest) or category already in Postgres; treating as synced",
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
                raise RuntimeError("Unexpected hub response when creating category")
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
                raise RuntimeError("Unexpected hub response when paging categories")
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
            raise RuntimeError("Unexpected hub response when paging providers")

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
            raise RuntimeError("Unexpected hub response when paging products")

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
        log_sync_step(
            "hub.push.batch.start",
            url=url,
            items=len(items),
            hub_base=self._base,
        )
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.post(
                    url,
                    json=json_safe({"items": items}),
                    headers=headers,
                )
        except httpx.HTTPError as exc:
            hint = ""
            err = str(exc).lower()
            if "ssl" in err or "record layer" in err:
                hint = (
                    " (HUB_BASE_URL uses https but hub listens on HTTP? "
                    "Use http://10.66.0.1:3000 on VPN dev)"
                )
            log_sync_error("hub.push.batch.failed", exc, url=url, items=len(items))
            raise RuntimeError(f"Hub unreachable on push batch: {exc}{hint}") from exc

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
            log_sync_step(
                "hub.push.batch.http_error",
                url=url,
                status=resp.status_code,
                detail=detail[:200],
            )
            raise RuntimeError(
                f"Hub push batch HTTP {resp.status_code}: {detail}"
            ) from None
        data = resp.json()
        if isinstance(data, dict):
            log_sync_step(
                "hub.push.batch.ok",
                url=url,
                items=len(items),
                inserted=data.get("inserted"),
                conflicts=data.get("conflicts"),
            )
            return data
        raise RuntimeError("Unexpected hub response on push batch")

    async def get_sync_job(self, job_id: str) -> dict:
        url = f"{self._base}{settings.hub_nodo_sync_jobs_path}/{job_id}"
        headers = {"Authorization": f"Bearer {settings.nodo_api_token}"}
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, dict):
                return data
            return {"jobId": job_id}

    async def patch_sync_job_progress(
        self, job_id: str, body: dict
    ) -> dict:
        url = f"{self._base}{settings.hub_nodo_sync_jobs_path}/{job_id}/progress"
        headers = {
            "Authorization": f"Bearer {settings.nodo_api_token}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.patch(url, json=json_safe(body), headers=headers)
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, dict):
                return data
            return {"ok": True}

    async def upload_sync_job_file(self, job_id: str, file_path) -> dict:
        from pathlib import Path

        path = Path(file_path)
        url = f"{self._base}{settings.hub_nodo_sync_jobs_path}/{job_id}/upload"
        headers = {
            "Authorization": f"Bearer {settings.nodo_api_token}",
            "Content-Type": "application/gzip",
        }
        async with httpx.AsyncClient(timeout=600.0) as client:
            with path.open("rb") as fh:
                resp = await client.post(url, content=fh.read(), headers=headers)
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, dict):
                return data
            return {"ok": True}

    async def download_sync_job_file(self, job_id: str, dest_path) -> None:
        from pathlib import Path

        path = Path(dest_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        url = f"{self._base}{settings.hub_nodo_sync_jobs_path}/{job_id}/download"
        headers = {"Authorization": f"Bearer {settings.nodo_api_token}"}
        async with httpx.AsyncClient(timeout=600.0) as client:
            async with client.stream("GET", url, headers=headers) as resp:
                resp.raise_for_status()
                with path.open("wb") as fh:
                    async for chunk in resp.aiter_bytes():
                        fh.write(chunk)
