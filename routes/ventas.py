from fastapi import APIRouter, Depends, HTTPException, Query

import anyio

from core.config import settings
from db.mysql import MySqlClient
from middleware.auth import verify_bearer

router = APIRouter(prefix="/api", tags=["ventas"])


def _fetch_ventas(
    search: str,
    fecha_desde: str,
    fecha_hasta: str,
    page: int,
    limit: int,
) -> tuple[list[dict], int]:
    mysql = MySqlClient()
    if not mysql.is_configured():
        raise RuntimeError("Node MySQL not configured (set MYSQL_* in env.txt/.env)")

    q = (search or "").strip()
    d = (fecha_desde or "").strip()
    h = (fecha_hasta or "").strip()
    like = f"%{q}%"
    offset = max(0, (page - 1) * limit)

    conn = mysql.connect()
    try:
        cur = conn.cursor(dictionary=True)
        where = "WHERE (%s = '' OR numfac LIKE %s OR codcli LIKE %s)"
        params: list = [q, like, like]

        if d:
            where += " AND fecfac >= %s"
            params.append(d)
        if h:
            where += " AND fecfac <= %s"
            params.append(h)

        cur.execute(
            f"""
            SELECT COUNT(*) AS cnt
            FROM sfac
            {where}
            """,
            tuple(params),
        )
        total_row = cur.fetchone() or {}
        total = int(total_row.get("cnt") or 0)

        cur.execute(
            f"""
            SELECT
              numfac,
              codcli,
              fecfac,
              tgrav,
              texent,
              timpu,
              tdesc,
              tfact
            FROM sfac
            {where}
            ORDER BY fecfac DESC, numfac DESC
            LIMIT %s OFFSET %s
            """,
            (*params, int(limit), int(offset)),
        )
        rows = cur.fetchall() or []
        return list(rows), total
    finally:
        conn.close()


def _get_venta(numfac: str) -> dict | None:
    mysql = MySqlClient()
    if not mysql.is_configured():
        raise RuntimeError("Node MySQL not configured (set MYSQL_* in env.txt/.env)")

    conn = mysql.connect()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            """
            SELECT
              numfac,
              codcli,
              fecfac,
              tgrav,
              texent,
              timpu,
              tdesc,
              tfact
            FROM sfac
            WHERE numfac = %s
            LIMIT 1
            """,
            (numfac,),
        )
        return cur.fetchone()
    finally:
        conn.close()


def _get_venta_detalle(numfac: str) -> list[dict]:
    mysql = MySqlClient()
    if not mysql.is_configured():
        raise RuntimeError("Node MySQL not configured (set MYSQL_* in env.txt/.env)")

    conn = mysql.connect()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            """
            SELECT
              numfac,
              codigo,
              descrip,
              cantidad,
              precio,
              pdescu,
              timpu,
              subtotal
            FROM sfacd
            WHERE numfac = %s
            ORDER BY numfac ASC
            """,
            (numfac,),
        )
        return list(cur.fetchall() or [])
    finally:
        conn.close()


@router.get("/ventas")
async def list_ventas(
    search: str = Query("", description="Match numfac or client code"),
    fecha_desde: str = Query("", description="Start date (YYYY-MM-DD)"),
    fecha_hasta: str = Query("", description="End date (YYYY-MM-DD)"),
    page: int = Query(1, ge=1, description="Page"),
    limit: int = Query(50, ge=1, le=500, description="Rows per page"),
    _: None = Depends(verify_bearer),
):
    items, total = await anyio.to_thread.run_sync(
        lambda: _fetch_ventas(search, fecha_desde, fecha_hasta, page, limit)
    )
    total_pages = 0 if total == 0 else (total + limit - 1) // limit
    return {
        "search": search,
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


@router.get("/ventas/{numfac}")
async def get_venta(numfac: str, _: None = Depends(verify_bearer)):
    venta = await anyio.to_thread.run_sync(lambda: _get_venta(numfac))
    if venta is None:
        raise HTTPException(status_code=404, detail="Venta not found")

    detalle = await anyio.to_thread.run_sync(lambda: _get_venta_detalle(numfac))
    return {
        "nodo_id": settings.nodo_id,
        "nombre": settings.nodo_nombre,
        "item": venta,
        "detalle": detalle,
        "message": "ok",
    }
