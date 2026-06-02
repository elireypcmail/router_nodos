"""Ids de eventos ingest hub (varchar 64 en nodo_ingested_events.event_id)."""

from __future__ import annotations

import hashlib

HUB_INGEST_EVENT_ID_MAX = 64


def bounded_event_id(*parts: str, max_len: int = HUB_INGEST_EVENT_ID_MAX) -> str:
    """Id determinista; si excede max_len, trunca prefijo y añade sha256 corto."""
    cleaned = [str(p).strip() or "-" for p in parts]
    raw = "-".join(cleaned)
    if len(raw) <= max_len:
        return raw
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    prefix_budget = max_len - 1 - len(digest)
    prefix = raw[:prefix_budget] if prefix_budget > 0 else digest
    return f"{prefix}-{digest}"
