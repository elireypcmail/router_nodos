from fastapi import APIRouter, Depends, HTTPException, Query

import anyio

from categories_models import CategoriaCreateRequest, CategoriaPatchRequest
from core.categoria_trace import trace, trace_exc, trace_warn
from core.config import settings
from db.mysql import MySqlClient
from middleware.auth import verify_bearer

router = APIRouter(prefix="/api/categorias", tags=["categorias"])


def _list_categorias(search: str, limit: int) -> list[dict]:
    trace("mysql.list.start", search=search, limit=limit)
    mysql = MySqlClient()
    if not mysql.is_configured():
        raise RuntimeError("Node MySQL not configured (set MYSQL_* in env.txt/.env)")

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
        raise RuntimeError("Node MySQL not configured (set MYSQL_* in env.txt/.env)")

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


def _create_categoria(body: CategoriaCreateRequest) -> None:
    trace(
        "mysql.create.start",
        ccate=body.ccate,
        ncate=body.ncate,
        pganancia=body.pganancia,
        pdescu=body.pdescu,
    )
    mysql = MySqlClient()
    if not mysql.is_configured():
        raise RuntimeError("Node MySQL not configured (set MYSQL_* in env.txt/.env)")

    conn = mysql.connect()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO catego (ccate, ncate, pganancia, pdescu)
            VALUES (%s, %s, %s, %s)
            """,
            (
                body.ccate.strip(),
                body.ncate.strip(),
                body.pganancia,
                body.pdescu,
            ),
        )
        conn.commit()
        trace("mysql.create.done", ccate=body.ccate)
    except Exception as exc:
        conn.rollback()
        trace_exc("mysql.create.failed", exc, ccate=body.ccate)
        raise
    finally:
        conn.close()


def _patch_categoria(ccate: str, patch: dict) -> int:
    trace(
        "mysql.patch.start",
        ccate=ccate,
        keys=sorted(patch.keys()),
    )
    mysql = MySqlClient()
    if not mysql.is_configured():
        raise RuntimeError("Node MySQL not configured (set MYSQL_* in env.txt/.env)")

    sets: list[str] = []
    vals: list[object] = []
    if "ncate" in patch and patch["ncate"] is not None:
        sets.append("ncate = %s")
        vals.append(str(patch["ncate"]).strip())
    if "pganancia" in patch:
        sets.append("pganancia = %s")
        vals.append(patch["pganancia"])
    if "pdescu" in patch:
        sets.append("pdescu = %s")
        vals.append(patch["pdescu"])
    if not sets:
        return 1

    conn = mysql.connect()
    try:
        cur = conn.cursor()
        vals.append(ccate)
        cur.execute(
            f"""
            UPDATE catego
            SET {", ".join(sets)}
            WHERE ccate = %s
            """,
            tuple(vals),
        )
        conn.commit()
        updated = int(cur.rowcount or 0)
        trace("mysql.patch.done", ccate=ccate, rowcount=updated)
        return updated
    except Exception as exc:
        conn.rollback()
        trace_exc("mysql.patch.failed", exc, ccate=ccate)
        raise
    finally:
        conn.close()


def _update_categoria(ccate: str, body: CategoriaPatchRequest) -> int:
    trace(
        "mysql.update.start",
        ccate=ccate,
        ncate=body.ncate,
        pganancia=body.pganancia,
        pdescu=body.pdescu,
    )
    mysql = MySqlClient()
    if not mysql.is_configured():
        raise RuntimeError("Node MySQL not configured (set MYSQL_* in env.txt/.env)")

    conn = mysql.connect()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE catego
            SET ncate = %s,
                pganancia = %s,
                pdescu = %s
            WHERE ccate = %s
            """,
            (
                body.ncate.strip(),
                body.pganancia,
                body.pdescu,
                ccate,
            ),
        )
        conn.commit()
        updated = int(cur.rowcount or 0)
        trace("mysql.update.done", ccate=ccate, rowcount=updated)
        return updated
    except Exception as exc:
        conn.rollback()
        trace_exc("mysql.update.failed", exc, ccate=ccate)
        raise
    finally:
        conn.close()


@router.get("")
async def list_categorias(
    search: str = Query("", description="Match code or name"),
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
        raise HTTPException(status_code=404, detail="Category not found")
    trace("rest.get.done", ccate=ccate)
    return {"nodo_id": settings.nodo_id, "item": item}


@router.post("")
async def create_categoria(body: CategoriaCreateRequest, _: None = Depends(verify_bearer)):
    trace("rest.create.start", ccate=body.ccate, ncate=body.ncate)
    local_item = await anyio.to_thread.run_sync(lambda: _get_categoria(body.ccate))
    if local_item is not None:
        trace_warn("rest.create.conflict", ccate=body.ccate)
        raise HTTPException(status_code=409, detail="Category already exists")

    payload = body.model_copy()
    if payload.pganancia is None:
        payload.pganancia = 0
    if payload.pdescu is None:
        payload.pdescu = 0

    await anyio.to_thread.run_sync(lambda: _create_categoria(payload))
    item = await anyio.to_thread.run_sync(lambda: _get_categoria(body.ccate))
    trace("rest.create.done", ccate=body.ccate)
    return {"nodo_id": settings.nodo_id, "item": item, "message": "ok"}


@router.patch("/{ccate}")
async def patch_categoria(
    ccate: str,
    body: CategoriaPatchRequest,
    _: None = Depends(verify_bearer),
):
    trace("rest.patch.start", ccate=ccate)
    local_item = await anyio.to_thread.run_sync(lambda: _get_categoria(ccate))
    if local_item is None:
        trace_warn("rest.patch.not_found", ccate=ccate)
        raise HTTPException(status_code=404, detail="Category not found")

    payload = body.model_dump(exclude_unset=True)
    if not payload:
        trace("rest.patch.noop", ccate=ccate)
        return {"nodo_id": settings.nodo_id, "item": local_item, "message": "ok"}

    updated = await anyio.to_thread.run_sync(lambda: _patch_categoria(ccate, payload))
    if updated == 0:
        trace_warn("rest.patch.not_found_after_update", ccate=ccate)
        raise HTTPException(status_code=404, detail="Category not found")

    item = await anyio.to_thread.run_sync(lambda: _get_categoria(ccate))
    trace("rest.patch.done", ccate=ccate)
    return {"nodo_id": settings.nodo_id, "item": item, "message": "ok"}
