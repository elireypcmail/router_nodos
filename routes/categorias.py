from fastapi import APIRouter, Depends, HTTPException, Query

import anyio

from categories_models import CategoriaCreateRequest, CategoriaPatchRequest
from core.categoria_trace import trace, trace_exc, trace_warn
from core.config import settings
from db.mysql import MySqlClient
from middleware.auth import verify_bearer

router = APIRouter(prefix="/api/categorias", tags=["categorias"])


def _catalog_like(term: str) -> str:
    return f"%{term.strip()}%"


def _fetch_categorias(
    search: str,
    codigo: str,
    nombre: str,
    page: int,
    limit: int,
) -> tuple[list[dict], int]:
    trace("mysql.list.start", search=search, codigo=codigo, nombre=nombre, page=page, limit=limit)
    mysql = MySqlClient()
    if not mysql.is_configured():
        raise RuntimeError("Node MySQL not configured (set MYSQL_* in env.txt/.env)")

    q = search.strip()
    c = codigo.strip()
    n = nombre.strip()
    like_search = _catalog_like(q) if q else None
    like_codigo = _catalog_like(c) if c else None
    like_nombre = _catalog_like(n) if n else None
    offset = max(0, (page - 1) * limit)

    conn = mysql.connect()
    try:
        cur = conn.cursor(dictionary=True)
        where = """
            WHERE 1=1
              AND (%s = '' OR ccate LIKE %s OR ncate LIKE %s)
              AND (%s = '' OR ccate LIKE %s)
              AND (%s = '' OR ncate LIKE %s)
        """
        params = (
            q,
            like_search or "",
            like_search or "",
            c,
            like_codigo or "",
            n,
            like_nombre or "",
        )
        cur.execute(f"SELECT COUNT(*) AS cnt FROM catego {where}", params)
        total_row = cur.fetchone() or {}
        total = int(total_row.get("cnt") or 0)

        cur.execute(
            f"""
            SELECT ccate, ncate, pganancia, pdescu
            FROM catego
            {where}
            ORDER BY ncate ASC
            LIMIT %s OFFSET %s
            """,
            (*params, int(limit), offset),
        )
        rows = list(cur.fetchall() or [])
        trace("mysql.list.done", count=len(rows), total=total)
        return rows, total
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
    codigo: str = Query("", description="Filter by code (partial)"),
    nombre: str = Query("", description="Filter by name (partial)"),
    page: int = Query(1, ge=1, description="Page"),
    limit: int = Query(25, ge=1, le=500, description="Rows per page"),
    _: None = Depends(verify_bearer),
):
    trace("rest.list.start", search=search, codigo=codigo, nombre=nombre, page=page, limit=limit)
    items, total = await anyio.to_thread.run_sync(
        lambda: _fetch_categorias(search, codigo, nombre, page, limit)
    )
    total_pages = 0 if total == 0 else (total + limit - 1) // limit
    trace("rest.list.done", count=len(items), total=total)
    return {
        "search": search,
        "codigo": codigo,
        "filtro_nombre": nombre,
        "nodo_id": settings.nodo_id,
        "items": items,
        "page": page,
        "limit": limit,
        "total": total,
        "totalPages": total_pages,
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
