"""Logs de apply-from-hub (catálogo / inventario) para depurar 400 en tienda."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("multishop.sync_apply")

# Campos del hub en inventario (sin volcar payloads enormes).
_INVENTARIO_LOG_KEYS = (
    "codigo",
    "ccate",
    "cod_prv",
    "descrip",
    "precio1",
    "porvg",
    "activo",
)


def row_summary(row: dict[str, Any] | None, *, keys: tuple[str, ...] = _INVENTARIO_LOG_KEYS) -> str:
    if not row or not isinstance(row, dict):
        return "{}"
    parts = [f"{k}={row.get(k)!r}" for k in keys if k in row]
    return " ".join(parts) if parts else f"keys={sorted(row.keys())}"


def log_apply_start(
    entity: str,
    *,
    require_local_dependencies: bool = False,
    row: dict[str, Any] | None = None,
) -> None:
    logger.info(
        "[apply-from-hub] %s start require_local_dependencies=%s %s",
        entity,
        require_local_dependencies,
        row_summary(row) if row else "",
    )


def log_apply_ok(entity: str, *, code: str = "") -> None:
    suffix = f" codigo={code}" if code else ""
    logger.info("[apply-from-hub] %s ok%s", entity, suffix)


def log_apply_value_error(
    entity: str,
    detail: str,
    *,
    require_local_dependencies: bool = False,
    row: dict[str, Any] | None = None,
) -> None:
    logger.warning(
        "[apply-from-hub] %s 400: %s | require_local_dependencies=%s %s",
        entity,
        detail,
        require_local_dependencies,
        row_summary(row),
    )


def log_apply_exception(
    entity: str,
    exc: BaseException,
    *,
    require_local_dependencies: bool = False,
    row: dict[str, Any] | None = None,
) -> None:
    logger.exception(
        "[apply-from-hub] %s error (%s): %s | require_local_dependencies=%s %s",
        entity,
        type(exc).__name__,
        exc,
        require_local_dependencies,
        row_summary(row),
    )
