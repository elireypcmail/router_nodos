"""Catálogo de bancos del nodo (tabla `banco`)."""

from __future__ import annotations

import anyio
from fastapi import APIRouter, Depends, HTTPException, Query

from core.config import settings
from db.mysql import MySqlClient
from middleware.auth import verify_bearer

router = APIRouter(prefix="/api/bancos", tags=["bancos"])


def _catalog_like(term: str) -> str:
    return f"%{term.strip()}%"


def _fetch_bancos(
    search: str,
    codigo: str,
    nombre: str,
    page: int,
    limit: int,
) -> tuple[list[dict], int]:
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
              AND (%s = '' OR cbanco LIKE %s OR nbanco LIKE %s)
              AND (%s = '' OR cbanco LIKE %s)
              AND (%s = '' OR nbanco LIKE %s)
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
        cur.execute(f"SELECT COUNT(*) AS cnt FROM banco {where}", params)
        total_row = cur.fetchone() or {}
        total = int(total_row.get("cnt") or 0)

        cur.execute(
            f"""
            SELECT
              cbanco,
              nbanco,
              COALESCE(cmoneda, '03') AS cmoneda
            FROM banco
            {where}
            ORDER BY CAST(cbanco AS UNSIGNED) ASC, cbanco ASC
            LIMIT %s OFFSET %s
            """,
            (*params, int(limit), offset),
        )
        return list(cur.fetchall() or []), total
    finally:
        conn.close()


def _get_banco(cbanco: str) -> dict | None:
    mysql = MySqlClient()
    if not mysql.is_configured():
        raise RuntimeError("Node MySQL not configured (set MYSQL_* in env.txt/.env)")

    code = cbanco.strip()[:10]
    if not code:
        return None

    conn = mysql.connect()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            """
            SELECT
              cbanco,
              nbanco,
              COALESCE(cmoneda, '03') AS cmoneda
            FROM banco
            WHERE cbanco = %s
            LIMIT 1
            """,
            (code,),
        )
        return cur.fetchone()
    finally:
        conn.close()


@router.get("")
async def list_bancos(
    search: str = Query("", description="Match code or name"),
    codigo: str = Query("", description="Filter by code (partial)"),
    nombre: str = Query("", description="Filter by name (partial)"),
    page: int = Query(1, ge=1, description="Page"),
    limit: int = Query(25, ge=1, le=500, description="Rows per page"),
    _: None = Depends(verify_bearer),
):
    try:
        items, total = await anyio.to_thread.run_sync(
            lambda: _fetch_bancos(search, codigo, nombre, page, limit)
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    total_pages = 0 if total == 0 else (total + limit - 1) // limit
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


@router.get("/{cbanco}")
async def get_banco(cbanco: str, _: None = Depends(verify_bearer)):
    try:
        item = await anyio.to_thread.run_sync(lambda: _get_banco(cbanco))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if not item:
        raise HTTPException(status_code=404, detail="Bank not found")
    return {"nodo_id": settings.nodo_id, "item": item, "message": "ok"}
