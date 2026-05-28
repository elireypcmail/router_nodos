"""Logs de peticiones /api/sync/* y llamadas salientes al hub (push/pull)."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import Request
from starlette.responses import Response

logger = logging.getLogger("multishop-nodo-api.sync")


def log_sync_step(step: str, **fields: Any) -> None:
    if fields:
        logger.info("%s | %s", step, " ".join(f"{k}={v!r}" for k, v in fields.items()))
    else:
        logger.info(step)


def log_sync_error(step: str, exc: BaseException, **fields: Any) -> None:
    suffix = ""
    if fields:
        suffix = " | " + " ".join(f"{k}={v!r}" for k, v in fields.items())
    logger.error(
        "%s%s | %s: %s",
        step,
        suffix,
        exc.__class__.__name__,
        exc,
        exc_info=(type(exc), exc, exc.__traceback__),
    )


async def sync_http_log_middleware(request: Request, call_next) -> Response:
    path = request.url.path
    if not path.startswith("/api/sync/"):
        return await call_next(request)

    client = request.client.host if request.client else None
    log_sync_step("sync.http.start", method=request.method, path=path, client=client)
    try:
        response = await call_next(request)
        if response.status_code >= 400:
            log_sync_step(
                "sync.http.end",
                method=request.method,
                path=path,
                status=response.status_code,
            )
        else:
            log_sync_step(
                "sync.http.end",
                method=request.method,
                path=path,
                status=response.status_code,
            )
        return response
    except Exception as exc:
        log_sync_error(
            "sync.http.failed",
            exc,
            method=request.method,
            path=path,
            client=client,
        )
        raise
