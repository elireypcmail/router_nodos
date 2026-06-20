from fastapi import APIRouter, Depends, HTTPException, Query

import anyio

from core.config import settings
from db.mysql import MySqlClient
from middleware.auth import verify_bearer

router = APIRouter(prefix="/api", tags=["compras"])

# En Multishop ERP, `scom` guarda una fila por línea de compra (no hay cabecera separada).
# El documento se identifica por `numero`; varias filas comparten numero/fecha/cod_prv.

_SCOM_LINE_SELECT = """
  numero AS numcom,
  codigo,
  descrip,
  cantidad,
  costo,
  subtotal2 AS subtotal,
  descuento1,
  porvg,
  indice
"""

_SCOM_PURCHASE_SUMMARY_SELECT = """
  numero AS numcom,
  MAX(cod_prv) AS cod_prv,
  MAX(fecha) AS fecha,
  SUM(subtotal2) AS tfact,
  SUM(exento) AS exento,
  SUM(iva1) AS iva1,
  COUNT(*) AS lineas
"""


def _build_scom_filters(
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
      OR cod_prv LIKE %s
      OR codigo LIKE %s
      OR descrip LIKE %s
    )
    """
    params: list = [q, like, like, like, like]

    if d:
        where += " AND fecha >= %s"
        params.append(d)
    if h:
        where += " AND fecha <= %s"
        params.append(h)

    return where, params


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

    where, params = _build_scom_filters(search, fecha_desde, fecha_hasta)
    offset = max(0, (page - 1) * limit)

    conn = mysql.connect()
    try:
        cur = conn.cursor(dictionary=True)

        cur.execute(
            f"""
            SELECT COUNT(*) AS cnt
            FROM (
              SELECT numero
              FROM scom
              {where}
              GROUP BY numero
            ) compras
            """,
            tuple(params),
        )
        total_row = cur.fetchone() or {}
        total = int(total_row.get("cnt") or 0)

        cur.execute(
            f"""
            SELECT
              {_SCOM_PURCHASE_SUMMARY_SELECT}
            FROM scom
            {where}
            GROUP BY numero
            ORDER BY fecha DESC, numero DESC
            LIMIT %s OFFSET %s
            """,
            (*params, int(limit), int(offset)),
        )
        rows = cur.fetchall() or []
        return list(rows), total
    finally:
        conn.close()


def _get_compra(numero: str) -> dict | None:
    mysql = MySqlClient()
    if not mysql.is_configured():
        raise RuntimeError("Node MySQL not configured (set MYSQL_* in env.txt/.env)")

    conn = mysql.connect()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            f"""
            SELECT
              {_SCOM_PURCHASE_SUMMARY_SELECT}
            FROM scom
            WHERE numero = %s
            GROUP BY numero
            LIMIT 1
            """,
            (numero,),
        )
        return cur.fetchone()
    finally:
        conn.close()


def _get_compra_detalle(numero: str) -> list[dict]:
    mysql = MySqlClient()
    if not mysql.is_configured():
        raise RuntimeError("Node MySQL not configured (set MYSQL_* in env.txt/.env)")

    conn = mysql.connect()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            f"""
            SELECT
              {_SCOM_LINE_SELECT}
            FROM scom
            WHERE numero = %s
            ORDER BY indice ASC, codigo ASC
            """,
            (numero,),
        )
        return list(cur.fetchall() or [])
    finally:
        conn.close()


@router.get("/compras")
async def list_compras(
    search: str = Query(
        "",
        description="Match purchase number, supplier code, SKU or description",
    ),
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


@router.get("/compras/{numero}")
async def get_compra(numero: str, _: None = Depends(verify_bearer)):
    compra = await anyio.to_thread.run_sync(lambda: _get_compra(numero))
    if compra is None:
        raise HTTPException(status_code=404, detail="Compra not found")

    detalle = await anyio.to_thread.run_sync(lambda: _get_compra_detalle(numero))
    return {
        "nodo_id": settings.nodo_id,
        "nombre": settings.nodo_nombre,
        "item": compra,
        "detalle": detalle,
        "message": "ok",
    }
