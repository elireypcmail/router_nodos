from fastapi import APIRouter, Depends, HTTPException, Query

import anyio

from categories_models import CategoriaUpsertRequest
from categoria_trace import trace, trace_exc, trace_warn
from config import settings
from db_mysql import MySqlClient
from hub_client import HubClient
from middleware.auth import verify_bearer

router = APIRouter(prefix="/api/categorias", tags=["categorias"])


def _list_categorias(search: str, limit: int) -> list[dict]:
    trace("mysql.list.start", search=search, limit=limit)
    mysql = MySqlClient()
    if not mysql.is_configured():
        raise RuntimeError("Node MySQL not configured (set MYSQL_* in .env)")

    q = search.strip()
    like = f"%{q}%"

    conn = mysql.connect()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            """
            SELECT ccate, ncate, pganancia, pdescu
            FROM catego
            WHERE (%s = '' OR ccate LIKE %s OR ncate LIKE %s)
            ORDER BY ncate ASC
            LIMIT %s
            """,
            (q, like, like, int(limit)),
        )
        rows = cur.fetchall() or []
        trace("mysql.list.done", count=len(rows))
        return rows
    finally:
        conn.close()


def _get_categoria(ccate: str) -> dict | None:
    trace("mysql.get.start", ccate=ccate)
    mysql = MySqlClient()
    if not mysql.is_configured():
        raise RuntimeError("Node MySQL not configured (set MYSQL_* in .env)")

    conn = mysql.connect()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            """
            SELECT ccate, ncate, pganancia, pdescu
            FROM catego
            WHERE ccate = %s
            LIMIT 1
            """,
            (ccate,),
        )
        row = cur.fetchone()
        trace("mysql.get.done", ccate=ccate, found=row is not None)
        return row
    finally:
        conn.close()


def _upsert_categoria(body: CategoriaUpsertRequest) -> None:
    trace(
        "mysql.upsert.start",
        ccate=body.ccate,
        ncate=body.ncate,
        pganancia=body.pganancia,
        pdescu=body.pdescu,
    )
    mysql = MySqlClient()
    if not mysql.is_configured():
        raise RuntimeError("Node MySQL not configured (set MYSQL_* in .env)")

    conn = mysql.connect()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO catego (ccate, ncate, pganancia, pdescu)
            VALUES (%s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
              ncate = VALUES(ncate),
              pganancia = VALUES(pganancia),
              pdescu = VALUES(pdescu)
            """,
            (
                body.ccate.strip(),
                body.ncate.strip(),
                body.pganancia,
                body.pdescu,
            ),
        )
        conn.commit()
        trace("mysql.upsert.done", ccate=body.ccate)
    except Exception as exc:
        conn.rollback()
        trace_exc("mysql.upsert.failed", exc, ccate=body.ccate)
        raise
    finally:
        conn.close()


def _delete_categoria(ccate: str) -> int:
    trace("mysql.delete.start", ccate=ccate)
    mysql = MySqlClient()
    if not mysql.is_configured():
        raise RuntimeError("Node MySQL not configured (set MYSQL_* in .env)")

    conn = mysql.connect()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM catego WHERE ccate = %s", (ccate,))
        conn.commit()
        deleted = int(cur.rowcount or 0)
        trace("mysql.delete.done", ccate=ccate, rowcount=deleted)
        return deleted
    except Exception as exc:
        conn.rollback()
        trace_exc("mysql.delete.failed", exc, ccate=ccate)
        raise
    finally:
        conn.close()


@router.get("")
async def list_categorias(
    search: str = Query("", description="Filtro por código o nombre"),
    limit: int = Query(200, ge=1, le=2000),
    _: None = Depends(verify_bearer),
):
    trace("rest.list.start", search=search, limit=limit)
    items = await anyio.to_thread.run_sync(lambda: _list_categorias(search, limit))
    trace("rest.list.done", count=len(items))
    return {
        "search": search,
        "nodo_id": settings.nodo_id,
        "items": items,
        "message": "ok",
    }


@router.get("/{ccate}")
async def get_categoria(ccate: str, _: None = Depends(verify_bearer)):
    trace("rest.get.start", ccate=ccate)
    item = await anyio.to_thread.run_sync(lambda: _get_categoria(ccate))
    if not item:
        trace_warn("rest.get.not_found", ccate=ccate)
        raise HTTPException(status_code=404, detail="Categoria no encontrada")
    trace("rest.get.done", ccate=ccate)
    return {"nodo_id": settings.nodo_id, "item": item}


@router.post("")
async def upsert_categoria(
    body: CategoriaUpsertRequest,
    confirmar_hub: bool = Query(
        False,
        description="Si ccate ya existe en el hub, confirmar guardado en MySQL local y sync al hub",
    ),
    _: None = Depends(verify_bearer),
):
    trace("rest.upsert.start", ccate=body.ccate, ncate=body.ncate, confirmar_hub=confirmar_hub)
    local_item = await anyio.to_thread.run_sync(lambda: _get_categoria(body.ccate))
    is_new_local = local_item is None

    hub: HubClient | None = None
    if settings.hub_base_url:
        try:
            hub = HubClient()
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail=f"No se pudo inicializar cliente del hub: {exc}",
            ) from exc

    hub_item: dict | None = None
    if hub is not None:
        trace(
            "rest.upsert.hub_check.start",
            ccate=body.ccate,
            is_new_local=is_new_local,
        )
        try:
            hub_item = await hub.get_categoria_in_hub(body.ccate)
        except Exception as exc:
            trace_exc("rest.upsert.hub_check.failed", exc, ccate=body.ccate)
            raise HTTPException(
                status_code=503,
                detail=f"No se pudo consultar el hub antes de guardar: {exc}",
            ) from exc
        if hub_item is not None and is_new_local and not confirmar_hub:
            trace_warn("rest.upsert.hub_check.blocked", ccate=body.ccate)
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "categoria_existe_en_hub",
                    "message": (
                        "El código ya existe en el hub y no hay fila local. "
                        "Repite con confirmar_hub=true para crear en MySQL y alinear con el hub."
                    ),
                    "ccate": body.ccate,
                    "hub": hub_item,
                },
            )
        trace(
            "rest.upsert.hub_check.ok",
            ccate=body.ccate,
            exists_in_hub=hub_item is not None,
            is_new_local=is_new_local,
        )

    await anyio.to_thread.run_sync(lambda: _upsert_categoria(body))

    if hub is not None:
        try:
            trace("rest.upsert.hub_push.start", ccate=body.ccate)
            await hub.create_categoria_in_hub(body.model_dump())
            trace("rest.upsert.hub_push.done", ccate=body.ccate)
        except Exception as exc:
            trace_warn(
                "rest.upsert.hub_push.failed",
                ccate=body.ccate,
                error=str(exc),
                error_type=exc.__class__.__name__,
            )
    else:
        trace("rest.upsert.hub_push.skipped", reason="HUB_BASE_URL empty")

    item = await anyio.to_thread.run_sync(lambda: _get_categoria(body.ccate))
    trace("rest.upsert.done", ccate=body.ccate)
    return {"nodo_id": settings.nodo_id, "item": item, "message": "ok"}


@router.delete("/{ccate}")
async def delete_categoria(ccate: str, _: None = Depends(verify_bearer)):
    trace("rest.delete.start", ccate=ccate)
    deleted = await anyio.to_thread.run_sync(lambda: _delete_categoria(ccate))
    if deleted == 0:
        trace_warn("rest.delete.not_found", ccate=ccate)
        raise HTTPException(status_code=404, detail="Categoria no encontrada")
    trace("rest.delete.done", ccate=ccate)
    return {"nodo_id": settings.nodo_id, "deleted": True}
