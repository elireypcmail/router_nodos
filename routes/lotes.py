from fastapi import APIRouter, Depends, Query

import anyio

from core.config import settings
from db.lotes_store import count_lotes_groups, fetch_lotes_groups, lotes_where
from db.mysql import MySqlClient
from middleware.auth import verify_bearer

router = APIRouter(prefix="/api", tags=["lotes"])


def _fetch_lotes(
    codigo: str,
    page: int,
    limit: int,
) -> tuple[list[dict], int]:
    mysql = MySqlClient()
    if not mysql.is_configured():
        raise RuntimeError("Node MySQL not configured (set MYSQL_* in env.txt/.env)")

    offset = max(0, (page - 1) * limit)
    where_sql, params = lotes_where(codigo)

    conn = mysql.connect()
    try:
        cur = conn.cursor(dictionary=True)
        total = count_lotes_groups(cur, where_sql, params)
        rows = fetch_lotes_groups(cur, where_sql, params, limit=limit, offset=offset)
        return rows, total
    finally:
        conn.close()


@router.get("/lotes")
async def list_lotes(
    codigo: str = Query("", description="Filter by item code (exact)"),
    fecha_desde: str = Query("", description="Start date (YYYY-MM-DD)"),
    fecha_hasta: str = Query("", description="End date (YYYY-MM-DD)"),
    page: int = Query(1, ge=1, description="Page"),
    limit: int = Query(200, ge=1, le=2000, description="Rows per page"),
    _: None = Depends(verify_bearer),
):
    items, total = await anyio.to_thread.run_sync(lambda: _fetch_lotes(codigo, page, limit))
    total_pages = 0 if total == 0 else (total + limit - 1) // limit
    return {
        "codigo": codigo,
        "fecha_desde": fecha_desde,
        "fecha_hasta": fecha_hasta,
        "nodo_id": settings.nodo_id,
        "nombre": settings.nodo_nombre,
        "items": items,
        "page": page,
        "limit": limit,
        "total": total,
        "totalPages": total_pages,
        "message": "ok",
    }
