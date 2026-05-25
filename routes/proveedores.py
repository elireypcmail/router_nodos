from fastapi import APIRouter, Depends, HTTPException, Query

import anyio
from pydantic import BaseModel

from config import settings
from db_mysql import MySqlClient
from middleware.auth import verify_bearer

router = APIRouter(prefix="/api", tags=["proveedores"])


class ProveedorUpsertRequest(BaseModel):
    cod_prv: str
    nom_prv: str | None = None
    rif_prv: str | None = None
    nit_prv: str | None = None
    dir1_prv: str | None = None
    tel_prv: str | None = None
    email1_prv: str | None = None
    tipo_prv: str | None = None
    plazo1: int | None = None
    plazo2: int | None = None
    plazo3: int | None = None


def _fetch_proveedores(search: str, limit: int) -> list[dict]:
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
              cod_prv,
              nom_prv,
              rif_prv,
              nit_prv,
              tel_prv,
              email1_prv,
              tipo_prv,
              plazo1,
              plazo2,
              plazo3
            FROM sprv
            WHERE (%s = '' OR cod_prv LIKE %s OR nom_prv LIKE %s OR rif_prv LIKE %s)
            ORDER BY nom_prv ASC
            LIMIT %s
            """,
            (q, like, like, like, int(limit)),
        )
        rows = cur.fetchall() or []
        return list(rows)
    finally:
        conn.close()


def _get_proveedor(cod_prv: str) -> dict | None:
    mysql = MySqlClient()
    if not mysql.is_configured():
        raise RuntimeError("MySQL del nodo no configurado (MYSQL_* en .env)")

    conn = mysql.connect()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            """
            SELECT
              cod_prv,
              nom_prv,
              rif_prv,
              nit_prv,
              dir1_prv,
              tel_prv,
              email1_prv,
              tipo_prv,
              plazo1,
              plazo2,
              plazo3
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
        raise RuntimeError("MySQL del nodo no configurado (MYSQL_* en .env)")

    cod_prv = (body.cod_prv or "").strip()
    if not cod_prv:
        raise RuntimeError("cod_prv es requerido")

    conn = mysql.connect()
    try:
        cur = conn.cursor()

        rif_prv = (body.rif_prv or "").strip()
        nom_prv = (body.nom_prv or "").strip()
        if rif_prv and nom_prv:
            cur.execute("SELECT 1 FROM auxiliar WHERE cauxiliar = %s LIMIT 1", (rif_prv,))
            exists = cur.fetchone()
            if not exists:
                cur.execute(
                    """
                    INSERT INTO auxiliar (cauxiliar, nauxiliar, rif)
                    VALUES (%s, %s, %s)
                    """,
                    (rif_prv, nom_prv, rif_prv),
                )
        cur.execute(
            """
            UPDATE sprv
            SET
              nom_prv = %s,
              rif_prv = %s,
              nit_prv = %s,
              dir1_prv = %s,
              tel_prv = %s,
              email1_prv = %s,
              tipo_prv = %s,
              plazo1 = %s,
              plazo2 = %s,
              plazo3 = %s
            WHERE cod_prv = %s
            """,
            (
                body.nom_prv,
                body.rif_prv,
                body.nit_prv,
                body.dir1_prv,
                body.tel_prv,
                body.email1_prv,
                body.tipo_prv,
                body.plazo1,
                body.plazo2,
                body.plazo3,
                cod_prv,
            ),
        )
        if int(cur.rowcount or 0) == 0:
            cur.execute(
                """
                INSERT INTO sprv (
                  cod_prv,
                  nom_prv,
                  rif_prv,
                  nit_prv,
                  dir1_prv,
                  tel_prv,
                  email1_prv,
                  tipo_prv,
                  plazo1,
                  plazo2,
                  plazo3
                )
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                (
                    cod_prv,
                    body.nom_prv,
                    body.rif_prv,
                    body.nit_prv,
                    body.dir1_prv,
                    body.tel_prv,
                    body.email1_prv,
                    body.tipo_prv,
                    body.plazo1,
                    body.plazo2,
                    body.plazo3,
                ),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _delete_proveedor(cod_prv: str) -> int:
    mysql = MySqlClient()
    if not mysql.is_configured():
        raise RuntimeError("MySQL del nodo no configurado (MYSQL_* en .env)")

    conn = mysql.connect()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM sprv WHERE cod_prv = %s", (cod_prv,))
        conn.commit()
        return int(cur.rowcount or 0)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@router.get("/proveedores")
async def proveedores(
    search: str = Query("", description="Filtro por código/nombre/RIF"),
    limit: int = Query(100, ge=1, le=1000),
    _: None = Depends(verify_bearer),
):
    items = await anyio.to_thread.run_sync(lambda: _fetch_proveedores(search, limit))
    return {
        "search": search,
        "nodo_id": settings.nodo_id,
        "nombre": settings.nodo_nombre,
        "items": items,
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
