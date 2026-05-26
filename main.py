"""API del nodo multishop — orquestada por Nest vía VPN hub."""

from contextlib import asynccontextmanager
import logging
import os

import uvicorn
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from config import settings
from db_mysql import MySqlClient
from hub_client import HubClient
from outbox_mysql import OutboxRepository
from outbox_worker import OutboxWorker
from pull_worker import HubPullWorker
from routes import categorias, health, inventario, proveedores, sync
from sync_apply import SyncApplier
from sync_store import SyncStore
from sync_worker import SyncWorker
from categoria_trace import is_categoria_http_path, trace, trace_exc

sync_store: SyncStore | None = None
sync_worker: SyncWorker | None = None
outbox_repo: OutboxRepository | None = None
outbox_worker: OutboxWorker | None = None
pull_worker: HubPullWorker | None = None
logger = logging.getLogger("multishop-nodo-api")


def configure_logging() -> None:
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    if not logging.root.handlers:
        logging.basicConfig(
            level=level,
            format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        )
    else:
        logging.root.setLevel(level)
    logging.getLogger("multishop.categoria").setLevel(level)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global sync_store, sync_worker, outbox_repo, outbox_worker, pull_worker

    sync_store = SyncStore(settings.sync_db_path)
    await sync_store.init()

    mysql = MySqlClient()
    applier = SyncApplier(mysql)
    sync_worker = SyncWorker(
        sync_store,
        applier.apply,
        poll_interval_seconds=settings.sync_worker_poll_interval_seconds,
    )
    if settings.sync_worker_enabled:
        sync_worker.start()

    if settings.hub_pull_enabled:
        hub = HubClient()
        pull_worker = HubPullWorker(
            sync_store,
            hub,
            interval_seconds=float(settings.hub_pull_interval_seconds),
            batch_size=int(settings.hub_pull_batch_size),
        )
        pull_worker.start()

    if settings.hub_push_enabled and not settings.huey_enabled:
        if not mysql.is_configured():
            raise RuntimeError("HUB_PUSH_ENABLED requiere MYSQL_* configurado")
        outbox_repo = OutboxRepository(mysql)
        outbox_repo.ensure_schema()
        hub = HubClient()
        outbox_worker = OutboxWorker(
            outbox_repo,
            hub,
            interval_seconds=settings.hub_push_interval_seconds,
        )
        outbox_worker.start()

    if settings.huey_enabled:
        if not mysql.is_configured():
            raise RuntimeError("HUEY_ENABLED requiere MYSQL_* configurado")
        outbox_repo = OutboxRepository(mysql)
        outbox_repo.ensure_schema()
        import huey_tasks

        huey_tasks.enqueue_outbox()

    try:
        yield
    finally:
        if sync_worker:
            await sync_worker.stop()
        if outbox_worker:
            await outbox_worker.stop()
        if pull_worker:
            await pull_worker.stop()


configure_logging()

app = FastAPI(
    title="Multishop Nodo",
    description="API HTTPS del nodo en tienda (red privada hub-spoke)",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(health.router)
app.include_router(inventario.router)
app.include_router(proveedores.router)
app.include_router(categorias.router)
app.include_router(sync.router)


@app.middleware("http")
async def categoria_http_trace(request: Request, call_next):
    path = request.url.path
    if not is_categoria_http_path(path):
        return await call_next(request)

    trace(
        "http.start",
        method=request.method,
        path=path,
        client=request.client.host if request.client else None,
    )
    try:
        response = await call_next(request)
        trace("http.end", method=request.method, path=path, status=response.status_code)
        return response
    except Exception as exc:
        trace_exc("http.failed", exc, method=request.method, path=path)
        raise


def _error_message(exc: Exception) -> str:
    message = str(exc).strip()
    return message or exc.__class__.__name__


@app.exception_handler(RequestValidationError)
async def request_validation_exception_handler(_request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={
            "error": "validation_error",
            "detail": "Payload inválido",
            "errors": exc.errors(),
        },
    )


@app.exception_handler(RuntimeError)
async def runtime_exception_handler(request: Request, exc: RuntimeError):
    message = _error_message(exc)
    logger.error("RuntimeError en %s %s: %s", request.method, request.url.path, message)
    return JSONResponse(
        status_code=500,
        content={
            "error": "runtime_error",
            "detail": message,
            "path": request.url.path,
        },
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    message = _error_message(exc)
    logger.exception("Error no controlado en %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={
            "error": "internal_error",
            "detail": message,
            "path": request.url.path,
            "type": exc.__class__.__name__,
        },
    )


@app.get("/")
async def root():
    return {"service": "multishop-nodo", "nodo_id": settings.nodo_id}


def run():
    import sys

    if sys.platform == "win32":
        import faulthandler

        faulthandler.enable()

    configure_logging()
    ssl_cert = settings.nodo_ssl_certfile or None
    ssl_key = settings.nodo_ssl_keyfile or None
    use_ssl = bool(ssl_cert and ssl_key)

    if not use_ssl and not settings.nodo_allow_insecure:
        raise RuntimeError(
            "Configure NODO_SSL_CERTFILE/NODO_SSL_KEYFILE o NODO_ALLOW_INSECURE=true (solo dev)"
        )

    uvicorn.run(
        "main:app",
        host=settings.nodo_host,
        port=settings.nodo_port,
        reload=False,
        ssl_certfile=ssl_cert if use_ssl else None,
        ssl_keyfile=ssl_key if use_ssl else None,
    )


if __name__ == "__main__":
    run()
