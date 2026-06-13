from fastapi import APIRouter, Depends, HTTPException, Query

import anyio

from core.config import settings
from db.mysql import MySqlClient
from middleware.auth import verify_bearer

router = APIRouter(prefix="/api", tags=["compras"])


def _fetch_compras(
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
        where = "WHERE (%s = '' OR numcom LIKE %s OR doc_prv LIKE %s)"
        params: list = [q, like, like]

        if d:
            where += " AND fecta >= %s"
            params.append(d)
        if h:
            where += " AND fecta <= %s"
            params.append(h)

        cur.execute(
            f"""
            SELECT COUNT(*) AS cnt
            FROM scom
            {where}
            """,
            tuple(params),
        )
        total_row = cur.fetchone() or {}
        total = int(total_row.get("cnt") or 0)

        cur.execute(
            f"""
            SELECT
              numcom,
              doc_prv,
              fecta,
              tgrav,
              texent,
              timpu,
              tdesc,
              tfact
            FROM scom
            {where}
            ORDER BY fecta DESC, numcom DESC
            LIMIT %s OFFSET %s
            """,
            (*params, int(limit), int(offset)),
        )
        rows = cur.fetchall() or []
        return list(rows), total
    finally:
        conn.close()


def _get_compra(numcom: str) -> dict | None:
    mysql = MySqlClient()
    if not mysql.is_configured():
        raise RuntimeError("Node MySQL not configured (set MYSQL_* in env.txt/.env)")

    conn = mysql.connect()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            """
            SELECT
              numcom,
              doc_prv,
              fecta,
              tgrav,
              texent,
              timpu,
              tdesc,
              tfact
            FROM scom
            WHERE numcom = %s
            LIMIT 1
            """,
            (numcom,),
        )
        return cur.fetchone()
    finally:
        conn.close()


def _get_compra_detalle(numcom: str) -> list[dict]:
    mysql = MySqlClient()
    if not mysql.is_configured():
        raise RuntimeError("Node MySQL not configured (set MYSQL_* in env.txt/.env)")

    conn = mysql.connect()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            """
            SELECT
              numcom,
              codigo,
              descrip,
              cantidad,
              costo,
              pdescu,
              timpu,
              subtotal
            FROM scomd
            WHERE numcom = %s
            ORDER BY numcom ASC
            """,
            (numcom,),
        )
        return list(cur.fetchall() or [])
    finally:
        conn.close()


@router.get("/compras")
async def list_compras(
    search: str = Query("", description="Match numcom or supplier doc"),
    fecha_desde: str = Query("", description="Start date (YYYY-MM-DD)"),
    fecha_hasta: str = Query("", description="End date (YYYY-MM-DD)"),
    page: int = Query(1, ge=1, description="Page"),
    limit: int = Query(50, ge=1, le=500, description="Rows per page"),
    _: None = Depends(verify_bearer),
):
    items, total = await anyio.to_thread.run_sync(
        lambda: _fetch_compras(search, fecha_desde, fecha_hasta, page, limit)
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


@router.get("/compras/{numcom}")
async def get_compra(numcom: str, _: None = Depends(verify_bearer)):
    compra = await anyio.to_thread.run_sync(lambda: _get_compra(numcom))
    if compra is None:
        raise HTTPException(status_code=404, detail="Compra not found")

    detalle = await anyio.to_thread.run_sync(lambda: _get_compra_detalle(numcom))
    return {
        "nodo_id": settings.nodo_id,
        "nombre": settings.nodo_nombre,
        "item": compra,
        "detalle": detalle,
        "message": "ok",
    }
