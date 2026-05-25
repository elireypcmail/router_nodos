"""API del nodo multishop — orquestada por Nest vía VPN hub."""

from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

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

sync_store: SyncStore | None = None
sync_worker: SyncWorker | None = None
outbox_repo: OutboxRepository | None = None
outbox_worker: OutboxWorker | None = None
pull_worker: HubPullWorker | None = None


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


@app.get("/")
async def root():
    return {"service": "multishop-nodo", "nodo_id": settings.nodo_id}


def run():
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
