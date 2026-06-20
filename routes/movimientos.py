from fastapi import APIRouter, Depends, HTTPException, Query

import anyio

from core.config import settings
from db.mysql import MySqlClient
from middleware.auth import verify_bearer

router = APIRouter(prefix="/api", tags=["movimientos"])

# Movimientos de inventario en Multishop ERP (tabla `kardex`).
_KARDEX_SELECT = """
  codigo,
  fecha,
  existenciai,
  entradas,
  salidas,
  existenciaf AS existencia,
  compras,
  ventas,
  devoc,
  devov,
  ajustesn,
  ajustesp,
  costo,
  costopro,
  numero AS documento,
  contador,
  indice,
  cajero,
  cod_cli,
  hora,
  kobs,
  CASE
    WHEN compras > 0 THEN 'compra'
    WHEN ventas > 0 THEN 'venta'
    WHEN devoc > 0 THEN 'devolucion_compra'
    WHEN devov > 0 THEN 'devolucion_venta'
    WHEN ajustesp <> 0 OR ajustesn <> 0 THEN 'ajuste'
    ELSE 'otro'
  END AS tipo,
  CASE
    WHEN ventas > 0 THEN -ventas
    WHEN compras > 0 THEN compras
    WHEN devov > 0 THEN devov
    WHEN devoc > 0 THEN -devoc
    WHEN ajustesp > 0 THEN ajustesp
    WHEN ajustesn > 0 THEN -ajustesn
    ELSE (entradas - salidas)
  END AS cantidad
"""

_TIPO_FILTERS: dict[str, str] = {
    "compra": "AND compras > 0",
    "venta": "AND ventas > 0",
    "ajuste": (
        "AND compras = 0 AND ventas = 0 AND devoc = 0 AND devov = 0 "
        "AND (ajustesp <> 0 OR ajustesn <> 0)"
    ),
    "devolucion_compra": "AND devoc > 0",
    "devolucion_venta": "AND devov > 0",
}


def _build_kardex_filters(
    codigo: str,
    desde: str,
    hasta: str,
    tipo: str,
) -> tuple[str, list]:
    where = "WHERE 1=1"
    params: list = []

    c = (codigo or "").strip()
    d = (desde or "").strip()
    h = (hasta or "").strip()
    t = (tipo or "").strip().lower()

    if c:
        where += " AND codigo = %s"
        params.append(c)
    if d:
        where += " AND fecha >= %s"
        params.append(d)
    if h:
        where += " AND fecha <= %s"
        params.append(h)

    tipo_filter = _TIPO_FILTERS.get(t)
    if tipo_filter:
        where += f" {tipo_filter}"

    return where, params


def _fetch_movimientos(
    codigo: str,
    desde: str,
    hasta: str,
    tipo: str,
    page: int,
    limit: int,
) -> tuple[list[dict], int]:
    mysql = MySqlClient()
    if not mysql.is_configured():
        raise RuntimeError("Node MySQL not configured (set MYSQL_* in env.txt/.env)")

    where, params = _build_kardex_filters(codigo, desde, hasta, tipo)
    offset = max(0, (page - 1) * limit)

    conn = mysql.connect()
    try:
        cur = conn.cursor(dictionary=True)

        cur.execute(
            f"""
            SELECT COUNT(*) AS cnt
            FROM kardex
            {where}
            """,
            tuple(params),
        )
        total_row = cur.fetchone() or {}
        total = int(total_row.get("cnt") or 0)

        cur.execute(
            f"""
            SELECT
              {_KARDEX_SELECT}
            FROM kardex
            {where}
            ORDER BY fecha DESC, indice DESC
            LIMIT %s OFFSET %s
            """,
            (*params, int(limit), int(offset)),
        )
        rows = cur.fetchall() or []
        return list(rows), total
    finally:
        conn.close()


@router.get("/movimientos")
async def list_movimientos(
    codigo: str = Query("", description="Filter by item code (exact)"),
    fecha_desde: str = Query("", description="Start date (YYYY-MM-DD)"),
    fecha_hasta: str = Query("", description="End date (YYYY-MM-DD)"),
    desde: str = Query("", description="Deprecated (use fecha_desde)"),
    hasta: str = Query("", description="Deprecated (use fecha_hasta)"),
    tipo: str = Query(
        "",
        description="compra|venta|ajuste|devolucion_compra|devolucion_venta",
    ),
    page: int = Query(1, ge=1, description="Page"),
    limit: int = Query(200, ge=1, le=2000, description="Rows per page"),
    _: None = Depends(verify_bearer),
):
    allowed = {
        "",
        "compra",
        "venta",
        "ajuste",
        "devolucion_compra",
        "devolucion_venta",
    }
    if tipo.strip().lower() not in allowed:
        raise HTTPException(status_code=422, detail="Invalid tipo")

    d = (fecha_desde or desde or "").strip()
    h = (fecha_hasta or hasta or "").strip()
    items, total = await anyio.to_thread.run_sync(
        lambda: _fetch_movimientos(codigo, d, h, tipo, page, limit)
    )
    total_pages = 0 if total == 0 else (total + limit - 1) // limit
    return {
        "codigo": codigo,
        "fecha_desde": d,
        "fecha_hasta": h,
        "tipo": tipo,
        "nodo_id": settings.nodo_id,
        "nombre": settings.nodo_nombre,
        "items": items,
        "page": page,
        "limit": limit,
        "total": total,
        "totalPages": total_pages,
        "message": "ok",
    }
