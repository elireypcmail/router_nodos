from fastapi import APIRouter, Depends, Query

import anyio

from core.config import settings
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

    c = (codigo or "").strip()
    offset = max(0, (page - 1) * limit)

    conn = mysql.connect()
    try:
        cur = conn.cursor(dictionary=True)
        where = "WHERE (%s = '' OR d.codigo = %s)"
        params = (c, c)

        cur.execute(
            f"""
            SELECT COUNT(*) AS cnt
            FROM detalle d
            {where}
            """,
            params,
        )
        total_row = cur.fetchone() or {}
        total = int(total_row.get("cnt") or 0)

        cur.execute(
            f"""
            SELECT
              d.codigo,
              d.indice,
              d.codigod,
              d.lote,
              d.cubica,
              u.nubica,
              d.existencia,
              d.vence,
              d.elabora,
              d.calidad,
              d.costo,
              d.costopr,
              d.costopro,
              d.costopropr,
              d.disponible,
              d.traslado
            FROM detalle d
            LEFT JOIN ubica u ON d.cubica = u.cubica
            {where}
            ORDER BY d.codigo ASC, d.cubica ASC, d.lote ASC, d.vence ASC
            LIMIT %s OFFSET %s
            """,
            (*params, int(limit), int(offset)),
        )
        rows = cur.fetchall() or []
        return list(rows), total
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
