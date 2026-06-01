from __future__ import annotations

from typing import Any

from hub.client import HubClient


def resolve_job_entity_type(job_meta: dict[str, Any]) -> str:
    raw = job_meta.get("entityType") or job_meta.get("entity_type") or "inventory"
    return str(raw).strip().lower() or "inventory"


async def fetch_hub_job_meta(hub: HubClient, job_id: str) -> dict[str, Any]:
    meta = await hub.get_sync_job(job_id)
    if not isinstance(meta, dict):
        return {}
    return meta
