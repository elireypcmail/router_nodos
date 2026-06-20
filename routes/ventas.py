from fastapi import APIRouter, Depends, HTTPException, Query

import anyio

from core.config import settings
from db.mysql import MySqlClient
from middleware.auth import verify_bearer

router = APIRouter(prefix="/api", tags=["ventas"])

# En Multishop ERP, `ventasi` guarda una fila por línea de venta (no hay cabecera separada).
# El documento se identifica por `numero`; varias filas comparten numero/fecha/cod_cli.

_VENTASI_LINE_SELECT = """
  numero AS numfac,
  codigo,
  descrip,
  cantidad,
  precio1 AS precio,
  subtotal2 AS subtotal,
  descuento1,
  porvg,
  contador,
  numerocf,
  ccaja
"""

_VENTASI_SUMMARY_SELECT = """
  numero AS numfac,
  MAX(cod_cli) AS codcli,
  MAX(fecha) AS fecfac,
  SUM(subtotal2) AS tfact,
  SUM(exento) AS exento,
  SUM(iva1) AS iva1,
  COUNT(*) AS lineas
"""


def _build_ventasi_filters(
    search: str,
    fecha_desde: str,
    fecha_hasta: str,
) -> tuple[str, list]:
    q = (search or "").strip()
    d = (fecha_desde or "").strip()
    h = (fecha_hasta or "").strip()
    like = f"%{q}%"

    where = """
    WHERE (
      %s = ''
      OR numero LIKE %s
      OR cod_cli LIKE %s
      OR codigo LIKE %s
      OR descrip LIKE %s
      OR numerocf LIKE %s
    )
    """
    params: list = [q, like, like, like, like, like]

    if d:
        where += " AND fecha >= %s"
        params.append(d)
    if h:
        where += " AND fecha <= %s"
        params.append(h)

    return where, params


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

    where, params = _build_ventasi_filters(search, fecha_desde, fecha_hasta)
    offset = max(0, (page - 1) * limit)

    conn = mysql.connect()
    try:
        cur = conn.cursor(dictionary=True)

        cur.execute(
            f"""
            SELECT COUNT(*) AS cnt
            FROM (
              SELECT numero
              FROM ventasi
              {where}
              GROUP BY numero
            ) ventas
            """,
            tuple(params),
        )
        total_row = cur.fetchone() or {}
        total = int(total_row.get("cnt") or 0)

        cur.execute(
            f"""
            SELECT
              {_VENTASI_SUMMARY_SELECT}
            FROM ventasi
            {where}
            GROUP BY numero
            ORDER BY fecfac DESC, numfac DESC
            LIMIT %s OFFSET %s
            """,
            (*params, int(limit), int(offset)),
        )
        rows = cur.fetchall() or []
        return list(rows), total
    finally:
        conn.close()


def _get_venta(numero: str) -> dict | None:
    mysql = MySqlClient()
    if not mysql.is_configured():
        raise RuntimeError("Node MySQL not configured (set MYSQL_* in env.txt/.env)")

    conn = mysql.connect()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            f"""
            SELECT
              {_VENTASI_SUMMARY_SELECT}
            FROM ventasi
            WHERE numero = %s
            GROUP BY numero
            LIMIT 1
            """,
            (numero,),
        )
        return cur.fetchone()
    finally:
        conn.close()


def _get_venta_detalle(numero: str) -> list[dict]:
    mysql = MySqlClient()
    if not mysql.is_configured():
        raise RuntimeError("Node MySQL not configured (set MYSQL_* in env.txt/.env)")

    conn = mysql.connect()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            f"""
            SELECT
              {_VENTASI_LINE_SELECT}
            FROM ventasi
            WHERE numero = %s
            ORDER BY contador ASC, codigo ASC
            """,
            (numero,),
        )
        return list(cur.fetchall() or [])
    finally:
        conn.close()


@router.get("/ventas")
async def list_ventas(
    search: str = Query(
        "",
        description="Match sale number, client code, fiscal number, SKU or description",
    ),
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


@router.get("/ventas/{numero}")
async def get_venta(numero: str, _: None = Depends(verify_bearer)):
    venta = await anyio.to_thread.run_sync(lambda: _get_venta(numero))
    if venta is None:
        raise HTTPException(status_code=404, detail="Venta not found")

    detalle = await anyio.to_thread.run_sync(lambda: _get_venta_detalle(numero))
    return {
        "nodo_id": settings.nodo_id,
        "nombre": settings.nodo_nombre,
        "item": venta,
        "detalle": detalle,
        "message": "ok",
    }
