"""Multishop store node API - orchestrated by Nest hub over VPN."""

from contextlib import asynccontextmanager
import logging
import os
from pathlib import Path
import ssl

from core.log_compat import configure_node_logging, ascii_safe

import pymysql
import uvicorn
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from core.config import settings
from core.json_util import json_safe
from routes import categorias, compras, health, inventario, laboratorios, lotes, movimientos, proveedores, ventas
from core.categoria_trace import is_categoria_http_path, trace, trace_exc

logger = logging.getLogger("multishop-nodo-api")


def configure_logging() -> None:
    configure_node_logging()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    yield


configure_logging()

app = FastAPI(
    title="Multishop Nodo",
    description="Store node HTTPS API (private hub-spoke network)",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(health.router)
app.include_router(inventario.router)
app.include_router(proveedores.router)
app.include_router(categorias.router)
app.include_router(laboratorios.router)
app.include_router(lotes.router)
app.include_router(compras.router)
app.include_router(ventas.router)
app.include_router(movimientos.router)


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
    return ascii_safe(message or exc.__class__.__name__)


@app.exception_handler(RequestValidationError)
async def request_validation_exception_handler(_request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={
            "error": "validation_error",
            "detail": "Invalid payload",
            "errors": json_safe(exc.errors()),
        },
    )


@app.exception_handler(pymysql.Error)
async def mysql_exception_handler(request: Request, exc: pymysql.Error):
    message = _error_message(exc)
    logger.error(
        "MySQL error on %s %s: %s",
        request.method,
        request.url.path,
        message,
        exc_info=True,
    )
    return JSONResponse(
        status_code=503,
        content={
            "error": "nodo_db_down",
            "code": "NODO_DB_DOWN",
            "detail": message,
            "path": request.url.path,
        },
    )


@app.exception_handler(RuntimeError)
async def runtime_exception_handler(request: Request, exc: RuntimeError):
    message = _error_message(exc)
    logger.error(
        "RuntimeError on %s %s: %s",
        request.method,
        request.url.path,
        message,
        exc_info=True,
    )

    if "requires MYSQL_* configured" in message or "Node MySQL not configured" in message:
        return JSONResponse(
            status_code=503,
            content={
                "error": "nodo_db_down",
                "code": "NODO_DB_NOT_CONFIGURED",
                "detail": message,
                "path": request.url.path,
            },
        )
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
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
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
    ssl_client_ca = settings.nodo_ssl_client_ca_file or None
    client_cert_required = bool(settings.nodo_ssl_client_cert_required)
    use_ssl = bool(ssl_cert and ssl_key)

    if not use_ssl and not settings.nodo_allow_insecure:
        raise RuntimeError(
            "Configure NODO_SSL_CERTFILE/NODO_SSL_KEYFILE or NODO_ALLOW_INSECURE=true (dev only)"
        )
    if client_cert_required and not use_ssl:
        raise RuntimeError(
            "mTLS requires TLS on node: configure NODO_SSL_CERTFILE/NODO_SSL_KEYFILE"
        )
    if client_cert_required and not ssl_client_ca:
        raise RuntimeError(
            "mTLS requires NODO_SSL_CLIENT_CA_FILE with hub CA certificate"
        )

    dev_reload = os.getenv("NODO_DEV_RELOAD", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )

    reload_kwargs: dict = {}
    if dev_reload:
        nodo_root = Path(__file__).resolve().parent
        # Solo .py del proyecto; evita bucle por __pycache__/venv/logs al reiniciar.
        reload_kwargs = {
            "reload_dirs": [str(nodo_root)],
            "reload_includes": ["*.py"],
            "reload_excludes": [
                "venv",
                "venv/**",
                ".venv",
                ".venv/**",
                "**/__pycache__",
                "**/__pycache__/**",
                "**/*.pyc",
                "**/*.pyo",
                ".env",
                ".env.*",
                "logs",
                "logs/**",
                "**/*.log",
            ],
            "reload_delay": 0.75,
        }

    print(settings.nodo_host)
    print(settings.nodo_port)

    uvicorn.run(
        "main:app",
        host=settings.nodo_host,
        port=settings.nodo_port,
        reload=dev_reload,
        ssl_certfile=ssl_cert if use_ssl else None,
        ssl_keyfile=ssl_key if use_ssl else None,
        ssl_ca_certs=ssl_client_ca if client_cert_required else None,
        ssl_cert_reqs=ssl.CERT_REQUIRED if client_cert_required else ssl.CERT_NONE,
        **reload_kwargs,
    )


if __name__ == "__main__":
    run()
