from fastapi import APIRouter, Depends, HTTPException, Query

import anyio

from core.config import settings
from db.mysql import MySqlClient
from middleware.auth import verify_bearer

router = APIRouter(prefix="/api", tags=["movimientos"])


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

    c = (codigo or "").strip()
    d = (desde or "").strip()
    h = (hasta or "").strip()
    t = (tipo or "").strip().lower()

    # Best-effort mapping; keeps endpoint functional even if the DB doesn't have all fields.
    tipo_where = ""
    if t in ("compra", "compras"):
        tipo_where = "AND (k.tipo = 'COMPRA' OR k.mov = 'C')"
    elif t in ("venta", "ventas"):
        tipo_where = "AND (k.tipo = 'VENTA' OR k.mov = 'V')"
    elif t:
        tipo_where = "AND (k.tipo = %s OR k.mov = %s)"

    offset = max(0, (page - 1) * limit)

    conn = mysql.connect()
    try:
        cur = conn.cursor(dictionary=True)

        base_where = "WHERE 1=1"
        params: list = []

        if c:
            base_where += " AND k.codigo = %s"
            params.append(c)

        if d:
            base_where += " AND k.fecha >= %s"
            params.append(d)

        if h:
            base_where += " AND k.fecha <= %s"
            params.append(h)

        if t and tipo_where:
            if "%s" in tipo_where:
                base_where += f" {tipo_where}"
                params.extend([t.upper(), t.upper()])
            else:
                base_where += f" {tipo_where}"

        cur.execute(
            f"""
            SELECT COUNT(*) AS cnt
            FROM kardex k
            {base_where}
            """,
            tuple(params),
        )
        total_row = cur.fetchone() or {}
        total = int(total_row.get("cnt") or 0)

        cur.execute(
            f"""
            SELECT
              k.codigo,
              k.fecha,
              k.mov,
              k.tipo,
              k.documento,
              k.entrada,
              k.salida,
              k.existencia,
              k.costo
            FROM kardex k
            {base_where}
            ORDER BY k.fecha DESC
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
    tipo: str = Query("", description="compra|venta|..."),
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
