"""Catálogo de cajas del nodo (tabla `cajero`)."""

from __future__ import annotations

import anyio
from fastapi import APIRouter, Depends, HTTPException, Query

from core.config import settings
from db.mysql import MySqlClient
from middleware.auth import verify_bearer

router = APIRouter(prefix="/api/cajeros", tags=["cajeros"])


def _catalog_like(term: str) -> str:
    return f"%{term.strip()}%"


def _fetch_cajeros(
    search: str,
    page: int,
    limit: int,
) -> tuple[list[dict], int]:
    mysql = MySqlClient()
    if not mysql.is_configured():
        raise RuntimeError("Node MySQL not configured (set MYSQL_* in env.txt/.env)")

    q = search.strip()
    like = _catalog_like(q) if q else None
    offset = max(0, (page - 1) * limit)

    conn = mysql.connect()
    try:
        cur = conn.cursor(dictionary=True)
        where = """
            WHERE 1=1
              AND (%s = '' OR ncaja LIKE %s OR TRIM(ccaja) LIKE %s)
        """
        params = (q, like or "", like or "")
        cur.execute(f"SELECT COUNT(*) AS cnt FROM cajero {where}", params)
        total_row = cur.fetchone() or {}
        total = int(total_row.get("cnt") or 0)

        cur.execute(
            f"""
            SELECT
              TRIM(ccaja) AS ccaja,
              TRIM(ncaja) AS ncaja,
              COALESCE(faccaj, 0) AS faccaj
            FROM cajero
            {where}
            ORDER BY CAST(TRIM(ccaja) AS UNSIGNED) ASC, TRIM(ccaja) ASC
            LIMIT %s OFFSET %s
            """,
            (*params, int(limit), offset),
        )
        return list(cur.fetchall() or []), total
    finally:
        conn.close()


@router.get("")
async def list_cajeros(
    search: str = Query("", description="Match ncaja or ccaja"),
    page: int = Query(1, ge=1, description="Page"),
    limit: int = Query(25, ge=1, le=500, description="Rows per page"),
    _: None = Depends(verify_bearer),
):
    try:
        items, total = await anyio.to_thread.run_sync(
            lambda: _fetch_cajeros(search, page, limit)
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    total_pages = 0 if total == 0 else (total + limit - 1) // limit
    return {
        "search": search,
        "nodo_id": settings.nodo_id,
        "items": items,
        "page": page,
        "limit": limit,
        "total": total,
        "totalPages": total_pages,
        "message": "ok",
    }
