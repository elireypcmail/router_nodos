from fastapi import APIRouter, Depends, HTTPException, Query

import anyio
from pydantic import BaseModel

from config import settings
from db_mysql import MySqlClient
from middleware.auth import verify_bearer

router = APIRouter(prefix="/api", tags=["inventario"])


class InventarioUpsertRequest(BaseModel):
    codigo: str
    descrip: str | None = None
    barra: str | None = None
    existencia: float | None = None
    precio1: float | None = None
    ccate: str | None = None
    cod_prv: str | None = None
    activo: int | None = None


def _fetch_inventario(search: str, limit: int) -> list[dict]:
    mysql = MySqlClient()
    if not mysql.is_configured():
        raise RuntimeError("MySQL del nodo no configurado (MYSQL_* en .env)")

    q = search.strip()
    like = f"%{q}%"
    conn = mysql.connect()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            """
            SELECT
              codigo,
              descrip,
              barra,
              existencia,
              precio1,
              ccate,
              cod_prv
            FROM sinv
            WHERE (%s = '' OR codigo LIKE %s OR descrip LIKE %s OR barra LIKE %s)
            ORDER BY descrip ASC
            LIMIT %s
            """,
            (q, like, like, like, int(limit)),
        )
        rows = cur.fetchall() or []
        return list(rows)
    finally:
        conn.close()


def _get_item(codigo: str) -> dict | None:
    mysql = MySqlClient()
    if not mysql.is_configured():
        raise RuntimeError("MySQL del nodo no configurado (MYSQL_* en .env)")

    conn = mysql.connect()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            """
            SELECT
              codigo,
              descrip,
              barra,
              existencia,
              precio1,
              ccate,
              cod_prv,
              activo
            FROM sinv
            WHERE codigo = %s
            LIMIT 1
            """,
            (codigo,),
        )
        return cur.fetchone()
    finally:
        conn.close()


def _upsert_item(body: InventarioUpsertRequest) -> None:
    mysql = MySqlClient()
    if not mysql.is_configured():
        raise RuntimeError("MySQL del nodo no configurado (MYSQL_* en .env)")

    codigo = (body.codigo or "").strip()
    if not codigo:
        raise RuntimeError("codigo es requerido")

    conn = mysql.connect()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO sinv (codigo, descrip, barra, existencia, precio1, ccate, cod_prv, activo)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
              descrip = VALUES(descrip),
              barra = VALUES(barra),
              existencia = VALUES(existencia),
              precio1 = VALUES(precio1),
              ccate = VALUES(ccate),
              cod_prv = VALUES(cod_prv),
              activo = VALUES(activo)
            """,
            (
                codigo,
                body.descrip,
                body.barra,
                body.existencia,
                body.precio1,
                body.ccate,
                body.cod_prv,
                body.activo,
            ),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _delete_item(codigo: str) -> int:
    mysql = MySqlClient()
    if not mysql.is_configured():
        raise RuntimeError("MySQL del nodo no configurado (MYSQL_* en .env)")

    conn = mysql.connect()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM sinv WHERE codigo = %s", (codigo,))
        conn.commit()
        return int(cur.rowcount or 0)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@router.get("/inventario")
async def inventario(
    search: str = Query("", description="Filtro por nombre o SKU"),
    limit: int = Query(50, ge=1, le=500, description="Máximo de resultados"),
    _: None = Depends(verify_bearer),
):
    items = await anyio.to_thread.run_sync(lambda: _fetch_inventario(search, limit))
    return {
        "search": search,
        "nodo_id": settings.nodo_id,
        "nombre": settings.nodo_nombre,
        "items": items,
        "message": "ok",
    }


@router.get("/inventario/{codigo}")
async def get_inventario_item(codigo: str, _: None = Depends(verify_bearer)):
    item = await anyio.to_thread.run_sync(lambda: _get_item(codigo))
    if not item:
        raise HTTPException(status_code=404, detail="Item no encontrado")
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
        raise HTTPException(status_code=404, detail="Item no encontrado")
    return {"nodo_id": settings.nodo_id, "deleted": True}
