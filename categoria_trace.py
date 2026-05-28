"""Unified category flow traces (REST, sync push/pull, hub, worker)."""

from __future__ import annotations

import logging
from typing import Any

from log_compat import ascii_safe

logger = logging.getLogger("multishop.categoria")

CATEGORIA_ENTITIES = frozenset(
    {"inventory_category", "categorias", "categoria", "catego"}
)


def is_categoria_entity(entity: str) -> bool:
    return (entity or "").strip().lower() in CATEGORIA_ENTITIES


def is_categoria_http_path(path: str) -> bool:
    p = (path or "").lower()
    return "/categorias" in p or p.rstrip("/") == "/api/sync/events"


def _format_fields(fields: dict[str, Any]) -> str:
    return " ".join(
        f"{k}={ascii_safe(v)!r}" if isinstance(v, str) else f"{k}={v!r}"
        for k, v in fields.items()
    )


def trace(step: str, **fields: Any) -> None:
    if fields:
        logger.info("[catego] %s | %s", step, _format_fields(fields))
    else:
        logger.info("[catego] %s", step)


def trace_warn(step: str, **fields: Any) -> None:
    if fields:
        logger.warning("[catego] %s | %s", step, _format_fields(fields))
    else:
        logger.warning("[catego] %s", step)


def trace_exc(step: str, exc: BaseException, **fields: Any) -> None:
    suffix = f" | {_format_fields(fields)}" if fields else ""
    logger.error(
        "[catego] %s%s | %s: %s",
        step,
        suffix,
        exc.__class__.__name__,
        exc,
        exc_info=(type(exc), exc, exc.__traceback__),
    )
