from fastapi import APIRouter, Depends, HTTPException, Query

import anyio
from pydantic import BaseModel

from config import settings
from db_mysql import MySqlClient
from sprv_store import delete_sprv, upsert_sprv
from middleware.auth import verify_bearer

router = APIRouter(prefix="/api", tags=["proveedores"])


class ProveedorUpsertRequest(BaseModel):
    cod_prv: str
    nom_prv: str | None = None
    rif_prv: str | None = None
    dir1_prv: str | None = None
    dir2_prv: str | None = None
    dir3_prv: str | None = None
    tel_prv: str | None = None
    email1_prv: str | None = None
    email2_prv: str | None = None
    rep_prv: str | None = None
    especial: str | None = None
    numcuenta: str | None = None


def _catalog_like(term: str) -> str:
    return f"%{term.strip()}%"


def _fetch_proveedores(
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
              AND (%s = '' OR cod_prv LIKE %s OR nom_prv LIKE %s OR rif_prv LIKE %s)
              AND (%s = '' OR cod_prv LIKE %s)
              AND (%s = '' OR nom_prv LIKE %s)
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
        cur.execute(f"SELECT COUNT(*) AS cnt FROM sprv {where}", params)
        total_row = cur.fetchone() or {}
        total = int(total_row.get("cnt") or 0)

        cur.execute(
            f"""
            SELECT
              cod_prv,
              nom_prv,
              rif_prv,
              dir1_prv,
              dir2_prv,
              dir3_prv,
              tel_prv,
              email1_prv,
              email2_prv,
              rep_prv,
              especial,
              numcuenta
            FROM sprv
            {where}
            ORDER BY nom_prv ASC
            LIMIT %s OFFSET %s
            """,
            (*params, int(limit), int(offset)),
        )
        rows = cur.fetchall() or []
        return list(rows), total
    finally:
        conn.close()


def _get_proveedor(cod_prv: str) -> dict | None:
    mysql = MySqlClient()
    if not mysql.is_configured():
        raise RuntimeError("Node MySQL not configured (set MYSQL_* in .env)")

    conn = mysql.connect()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            """
            SELECT
              cod_prv,
              nom_prv,
              rif_prv,
              dir1_prv,
              dir2_prv,
              dir3_prv,
              tel_prv,
              email1_prv,
              email2_prv,
              rep_prv,
              especial,
              numcuenta
            FROM sprv
            WHERE cod_prv = %s
            LIMIT 1
            """,
            (cod_prv,),
        )
        return cur.fetchone()
    finally:
        conn.close()


def _upsert_proveedor(body: ProveedorUpsertRequest) -> None:
    mysql = MySqlClient()
    if not mysql.is_configured():
        raise RuntimeError("Node MySQL not configured (set MYSQL_* in .env)")

    cod_prv = (body.cod_prv or "").strip()
    if not cod_prv:
        raise RuntimeError("cod_prv is required")

    conn = mysql.connect()
    try:
        cur = conn.cursor()
        upsert_sprv(cur, body.model_dump())
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _delete_proveedor(cod_prv: str) -> int:
    mysql = MySqlClient()
    if not mysql.is_configured():
        raise RuntimeError("Node MySQL not configured (set MYSQL_* in .env)")

    conn = mysql.connect()
    try:
        cur = conn.cursor()
        deleted = delete_sprv(cur, cod_prv)
        conn.commit()
        return deleted
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@router.get("/proveedores")
async def proveedores(
    search: str = Query("", description="Coincidencia en código o nombre"),
    codigo: str = Query("", description="Filtro por código (parcial)"),
    nombre: str = Query("", description="Filtro por nombre (parcial)"),
    page: int = Query(1, ge=1, description="Página"),
    limit: int = Query(25, ge=1, le=500, description="Filas por página"),
    _: None = Depends(verify_bearer),
):
    items, total = await anyio.to_thread.run_sync(
        lambda: _fetch_proveedores(search, codigo, nombre, page, limit)
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


@router.get("/proveedores/{cod_prv}")
async def get_proveedor(cod_prv: str, _: None = Depends(verify_bearer)):
    item = await anyio.to_thread.run_sync(lambda: _get_proveedor(cod_prv))
    if not item:
        raise HTTPException(status_code=404, detail="Proveedor no encontrado")
    return {"nodo_id": settings.nodo_id, "item": item}


@router.post("/proveedores")
async def upsert_proveedor(body: ProveedorUpsertRequest, _: None = Depends(verify_bearer)):
    await anyio.to_thread.run_sync(lambda: _upsert_proveedor(body))
    item = await anyio.to_thread.run_sync(lambda: _get_proveedor(body.cod_prv))
    return {"nodo_id": settings.nodo_id, "item": item, "message": "ok"}


@router.delete("/proveedores/{cod_prv}")
async def delete_proveedor(cod_prv: str, _: None = Depends(verify_bearer)):
    deleted = await anyio.to_thread.run_sync(lambda: _delete_proveedor(cod_prv))
    if deleted == 0:
        raise HTTPException(status_code=404, detail="Proveedor no encontrado")
    return {"nodo_id": settings.nodo_id, "deleted": True}
