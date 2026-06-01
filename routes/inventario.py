from fastapi import APIRouter, Depends, HTTPException, Query

import anyio
from pydantic import BaseModel

from core.config import settings
from db.mysql import MySqlClient
from db.sinv_store import delete_sinv, upsert_sinv
from middleware.auth import verify_bearer

router = APIRouter(prefix="/api", tags=["inventario"])


class InventarioUpsertRequest(BaseModel):
    codigo: str
    descrip: str | None = None
    ccate: str | None = None
    cod_prv: str | None = None
    precio1: float | None = None
    pg1: float | None = None
    barra: str | None = None
    referencia: str | None = None
    componente: str | None = None
    stockmin: float | None = None
    stockmax: float | None = None
    recipe: int | None = None
    cfrio: int | None = None
    activo: int | None = None
    existencia: float | None = None


def _catalog_like(term: str) -> str:
    return f"%{term.strip()}%"


def _fetch_inventario(
    search: str,
    codigo: str,
    nombre: str,
    page: int,
    limit: int,
) -> tuple[list[dict], int]:
    mysql = MySqlClient()
    if not mysql.is_configured():
        raise RuntimeError("Node MySQL not configured (set MYSQL_* in .env)")

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
              AND (%s = '' OR codigo LIKE %s OR descrip LIKE %s OR barra LIKE %s)
              AND (%s = '' OR codigo LIKE %s)
              AND (%s = '' OR descrip LIKE %s)
        """
        params = (
            q,
            like_search or "",
            like_search or "",
            like_search or "",
            c,
            like_codigo or "",
            n,
            like_nombre or "",
        )
        cur.execute(f"SELECT COUNT(*) AS cnt FROM sinv {where}", params)
        total_row = cur.fetchone() or {}
        total = int(total_row.get("cnt") or 0)

        cur.execute(
            f"""
            SELECT
              codigo,
              descrip,
              ccate,
              cod_prv,
              precio1,
              pg1,
              porvg,
              precio2,
              precio3,
              precio4,
              precio5,
              pg2,
              pg3,
              pg4,
              pg5,
              precio1div,
              precio1ediv,
              pg1div,
              pg1ediv,
              pvjusto,
              barra,
              referencia,
              componente,
              stockmin,
              stockmax,
              recipe,
              cfrio,
              activo,
              existencia,
              costo,
              costopro,
              costoant
            FROM sinv
            {where}
            ORDER BY descrip ASC
            LIMIT %s OFFSET %s
            """,
            (*params, int(limit), int(offset)),
        )
        rows = cur.fetchall() or []
        return list(rows), total
    finally:
        conn.close()


def _get_item(codigo: str) -> dict | None:
    mysql = MySqlClient()
    if not mysql.is_configured():
        raise RuntimeError("Node MySQL not configured (set MYSQL_* in .env)")

    conn = mysql.connect()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            """
            SELECT
              codigo,
              descrip,
              ccate,
              cod_prv,
              precio1,
              pg1,
              porvg,
              precio2,
              precio3,
              precio4,
              precio5,
              pg2,
              pg3,
              pg4,
              pg5,
              precio1div,
              precio1ediv,
              pg1div,
              pg1ediv,
              pvjusto,
              barra,
              referencia,
              componente,
              stockmin,
              stockmax,
              recipe,
              cfrio,
              activo,
              existencia,
              costo,
              costopro,
              costoant,
              fultimav,
              fultimac
            FROM sinv
            WHERE codigo = %s
            LIMIT 1
            """,
            (codigo,),
        )
        return cur.fetchone()
    finally:
        conn.close()


def _fetch_lotes(codigo: str) -> list[dict]:
    mysql = MySqlClient()
    if not mysql.is_configured():
        raise RuntimeError("Node MySQL not configured (set MYSQL_* in .env)")

    conn = mysql.connect()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            """
            SELECT
              indice,
              codigod,
              lote,
              cubica,
              existencia,
              vence,
              elabora,
              calidad,
              costo,
              costopr,
              costopro,
              costopropr,
              disponible,
              traslado
            FROM detalle
            WHERE codigo = %s
            ORDER BY cubica ASC, lote ASC, vence ASC
            """,
            (codigo,),
        )
        return list(cur.fetchall() or [])
    finally:
        conn.close()


def _get_detalle_tienda(codigo: str) -> dict | None:
    item = _get_item(codigo)
    if not item:
        return None
    try:
        lotes = _fetch_lotes(codigo)
    except Exception:
        lotes = []
    existencia_lotes = sum(float(row.get("existencia") or 0) for row in lotes)
    return {
        "item": item,
        "lotes": lotes,
        "existencia_lotes": existencia_lotes,
    }


def _upsert_item(body: InventarioUpsertRequest) -> None:
    mysql = MySqlClient()
    if not mysql.is_configured():
        raise RuntimeError("Node MySQL not configured (set MYSQL_* in .env)")

    codigo = (body.codigo or "").strip()
    if not codigo:
        raise RuntimeError("codigo is required")

    conn = mysql.connect()
    try:
        cur = conn.cursor()
        payload = body.model_dump(exclude_unset=True)
        upsert_sinv(cur, payload, patch_keys=set(payload.keys()))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _delete_item(codigo: str) -> int:
    mysql = MySqlClient()
    if not mysql.is_configured():
        raise RuntimeError("Node MySQL not configured (set MYSQL_* in .env)")

    conn = mysql.connect()
    try:
        cur = conn.cursor()
        deleted = delete_sinv(cur, codigo)
        conn.commit()
        return deleted
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@router.get("/inventario")
async def inventario(
    search: str = Query("", description="Match code or description"),
    codigo: str = Query("", description="Filter by code (partial)"),
    nombre: str = Query("", description="Filter by description (partial)"),
    page: int = Query(1, ge=1, description="Page"),
    limit: int = Query(25, ge=1, le=500, description="Rows per page"),
    _: None = Depends(verify_bearer),
):
    items, total = await anyio.to_thread.run_sync(
        lambda: _fetch_inventario(search, codigo, nombre, page, limit)
    )
    total_pages = 0 if total == 0 else (total + limit - 1) // limit
    return {
        "search": search,
        "codigo": codigo,
        "filtro_nombre": nombre,
        "nodo_id": settings.nodo_id,
        "nombre": settings.nodo_nombre,
        "items": items,
        "page": page,
        "limit": limit,
        "total": total,
        "totalPages": total_pages,
        "message": "ok",
    }


@router.get("/inventario/{codigo}/detalle-tienda")
async def get_inventario_detalle_tienda(
    codigo: str, _: None = Depends(verify_bearer)
):
    payload = await anyio.to_thread.run_sync(lambda: _get_detalle_tienda(codigo))
    if not payload:
        raise HTTPException(status_code=404, detail="Item not found")
    return {
        "nodo_id": settings.nodo_id,
        "nombre": settings.nodo_nombre,
        **payload,
        "message": "ok",
    }


@router.get("/inventario/{codigo}")
async def get_inventario_item(codigo: str, _: None = Depends(verify_bearer)):
    item = await anyio.to_thread.run_sync(lambda: _get_item(codigo))
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    return {"nodo_id": settings.nodo_id, "item": item}


@router.post("/inventario")
async def upsert_inventario_item(body: InventarioUpsertRequest, _: None = Depends(verify_bearer)):
    await anyio.to_thread.run_sync(lambda: _upsert_item(body))
    item = await anyio.to_thread.run_sync(lambda: _get_item(body.codigo))
    return {"nodo_id": settings.nodo_id, "item": item, "message": "ok"}


@router.delete("/inventario/{codigo}")
async def delete_inventario_item(codigo: str, _: None = Depends(verify_bearer)):
    deleted = await anyio.to_thread.run_sync(lambda: _delete_item(codigo))
    if deleted == 0:
        raise HTTPException(status_code=404, detail="Item not found")
    return {"nodo_id": settings.nodo_id, "deleted": True}
