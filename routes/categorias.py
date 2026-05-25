from fastapi import APIRouter, Depends, HTTPException, Query

import anyio

from categories_models import CategoriaUpsertRequest
from config import settings
from db_mysql import MySqlClient
from hub_client import HubClient
from middleware.auth import verify_bearer

router = APIRouter(prefix="/api/categorias", tags=["categorias"])


def _list_categorias(search: str, limit: int) -> list[dict]:
    mysql = MySqlClient()
    if not mysql.is_configured():
        raise RuntimeError("MySQL del nodo no configurado (MYSQL_* en .env)")

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
        return cur.fetchall() or []
    finally:
        conn.close()


def _get_categoria(ccate: str) -> dict | None:
    mysql = MySqlClient()
    if not mysql.is_configured():
        raise RuntimeError("MySQL del nodo no configurado (MYSQL_* en .env)")

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
        return cur.fetchone()
    finally:
        conn.close()


def _upsert_categoria(body: CategoriaUpsertRequest) -> None:
    mysql = MySqlClient()
    if not mysql.is_configured():
        raise RuntimeError("MySQL del nodo no configurado (MYSQL_* en .env)")

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
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _delete_categoria(ccate: str) -> int:
    mysql = MySqlClient()
    if not mysql.is_configured():
        raise RuntimeError("MySQL del nodo no configurado (MYSQL_* en .env)")

    conn = mysql.connect()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM catego WHERE ccate = %s", (ccate,))
        conn.commit()
        return int(cur.rowcount or 0)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@router.get("")
async def list_categorias(
    search: str = Query("", description="Filtro por código o nombre"),
    limit: int = Query(200, ge=1, le=2000),
    _: None = Depends(verify_bearer),
):
    items = await anyio.to_thread.run_sync(lambda: _list_categorias(search, limit))
    return {
        "search": search,
        "nodo_id": settings.nodo_id,
        "items": items,
        "message": "ok",
    }


@router.get("/{ccate}")
async def get_categoria(ccate: str, _: None = Depends(verify_bearer)):
    item = await anyio.to_thread.run_sync(lambda: _get_categoria(ccate))
    if not item:
        raise HTTPException(status_code=404, detail="Categoria no encontrada")
    return {"nodo_id": settings.nodo_id, "item": item}


@router.post("")
async def upsert_categoria(body: CategoriaUpsertRequest, _: None = Depends(verify_bearer)):
    await anyio.to_thread.run_sync(lambda: _upsert_categoria(body))
    if settings.hub_base_url:
        try:
            hub = HubClient()
            await hub.create_categoria_in_hub(body.model_dump())
        except Exception:
            pass
    item = await anyio.to_thread.run_sync(lambda: _get_categoria(body.ccate))
    return {"nodo_id": settings.nodo_id, "item": item, "message": "ok"}


@router.delete("/{ccate}")
async def delete_categoria(ccate: str, _: None = Depends(verify_bearer)):
    deleted = await anyio.to_thread.run_sync(lambda: _delete_categoria(ccate))
    if deleted == 0:
        raise HTTPException(status_code=404, detail="Categoria no encontrada")
    return {"nodo_id": settings.nodo_id, "deleted": True}
