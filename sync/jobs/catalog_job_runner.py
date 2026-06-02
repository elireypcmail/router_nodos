from __future__ import annotations

from typing import Any

from hub.client import HubClient


def resolve_job_entity_type(job_meta: dict[str, Any]) -> str:
    raw = job_meta.get("entityType") or job_meta.get("entity_type") or "inventory"
    return str(raw).strip().lower() or "inventory"


def resolve_transaction_mode_from_entity(entity: str) -> str | None:
    key = entity.strip().lower()
    if key in ("transaction_purchase", "transactions_purchase"):
        return "purchase"
    if key in ("transaction_sale", "transactions_sale"):
        return "sale"
    if key == "transactions":
        return None
    return None


async def fetch_hub_job_meta(hub: HubClient, job_id: str) -> dict[str, Any]:
    meta = await hub.get_sync_job(job_id)
    if not isinstance(meta, dict):
        return {}
    return meta


def _job_options(meta: dict[str, Any]) -> dict[str, Any]:
    raw = meta.get("options")
    return raw if isinstance(raw, dict) else {}


def _purchase_upload_done(meta: dict[str, Any]) -> bool:
    status = str(meta.get("status") or "").strip().lower()
    if status in ("completed",):
        return True
    if status in ("failed", "cancelled", "interrupted"):
        raise RuntimeError(
            f"Job compras terminó en {status}: {meta.get('errorMessage') or meta.get('error_message') or ''}"
        )
    phase = str(meta.get("phase") or "").strip().lower()
    progress = meta.get("progressNodo")
    if progress is None:
        progress = meta.get("progress_nodo")
    try:
        progress_nodo = int(progress or 0)
    except (TypeError, ValueError):
        progress_nodo = 0
    if progress_nodo >= 100:
        return True
    return phase == "process"


async def wait_purchase_upload_before_sale_export(
    hub: HubClient,
    job_meta: dict[str, Any],
    *,
    poll_sec: float = 2.0,
    max_wait_sec: float = 4 * 3600,
) -> None:
    """No exportar ventas en tienda hasta que el job compras emparejado subió el .ndjson.gz."""
    import asyncio
    import logging
    import time

    opts = _job_options(job_meta)
    purchase_id = (
        opts.get("pairedPurchaseJobId") or opts.get("paired_purchase_job_id") or ""
    )
    purchase_id = str(purchase_id).strip()
    if not purchase_id:
        return

    log = logging.getLogger("multishop.catalog_job")
    deadline = time.monotonic() + max_wait_sec
    while time.monotonic() < deadline:
        purchase_meta = await fetch_hub_job_meta(hub, purchase_id)
        if _purchase_upload_done(purchase_meta):
            log.info(
                "Ventas: compras %s listas (upload); iniciando export ventas",
                purchase_id,
            )
            return
        await asyncio.sleep(poll_sec)
    raise TimeoutError(
        f"Tiempo agotado esperando upload de compras job={purchase_id}"
    )


def resolve_transaction_since(
    job_meta: dict[str, Any],
    mode: str,
) -> TransactionWatermark | None:
    from sync.jobs.transaction_sync_types import TransactionWatermark

    block = job_meta.get("transactionSyncSince") or job_meta.get(
        "transaction_sync_since"
    )
    if not isinstance(block, dict):
        return None
    raw = block.get(mode)
    if raw is None:
        return None
    return TransactionWatermark.from_dict(raw if isinstance(raw, dict) else None)
