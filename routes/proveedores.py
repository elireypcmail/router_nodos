from fastapi import APIRouter, Depends, HTTPException, Query

import anyio
from pydantic import BaseModel, Field

from core.config import settings
from db.mysql import MySqlClient
from db.sprv_store import upsert_sprv
from middleware.auth import verify_bearer

router = APIRouter(prefix="/api", tags=["proveedores"])

RIF_PATTERN = r"^[A-Za-z]\d+$"


class ProveedorCreateRequest(BaseModel):
    nom_prv: str = Field(min_length=1, max_length=240)
    rif_prv: str = Field(min_length=1, max_length=30, pattern=RIF_PATTERN)
    dir1_prv: str = Field(min_length=1, max_length=200)
    dir2_prv: str = Field(min_length=0, max_length=200)
    dir3_prv: str = Field(min_length=0, max_length=200)
    tel_prv: str = Field(min_length=1, max_length=80)
    email1_prv: str = Field(min_length=1, max_length=80)
    email2_prv: str | None = Field(default=None, max_length=200)
    rep_prv: str = Field(min_length=1, max_length=50)
    especial: str = Field(min_length=1, max_length=8)
    numcuenta: str = Field(min_length=1, max_length=30, pattern=r"^\d+$")


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


class ProveedorPatchRequest(BaseModel):
    nom_prv: str | None = Field(default=None, min_length=1, max_length=240)
    dir1_prv: str | None = Field(default=None, min_length=1, max_length=200)
    dir2_prv: str | None = Field(default=None, min_length=0, max_length=200)
    dir3_prv: str | None = Field(default=None, min_length=0, max_length=200)
    tel_prv: str | None = Field(default=None, min_length=1, max_length=80)
    email1_prv: str | None = Field(default=None, min_length=1, max_length=80)
    email2_prv: str | None = Field(default=None, max_length=200)
    rep_prv: str | None = Field(default=None, min_length=1, max_length=50)
    especial: str | None = Field(default=None, min_length=1, max_length=8)
    numcuenta: str | None = Field(
        default=None, min_length=1, max_length=30, pattern=r"^\d+$"
    )


def _normalize_rif(rif: str) -> str:
    return rif.strip()


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
        raise RuntimeError("Node MySQL not configured (set MYSQL_* in env.txt/.env)")

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
        raise RuntimeError("Node MySQL not configured (set MYSQL_* in env.txt/.env)")

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
        raise RuntimeError("Node MySQL not configured (set MYSQL_* in env.txt/.env)")

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


@router.get("/proveedores")
async def proveedores(
    search: str = Query("", description="Match code or name"),
    codigo: str = Query("", description="Filter by code (partial)"),
    nombre: str = Query("", description="Filter by name (partial)"),
    page: int = Query(1, ge=1, description="Page"),
    limit: int = Query(25, ge=1, le=500, description="Rows per page"),
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
        raise HTTPException(status_code=404, detail="Provider not found")
    return {"nodo_id": settings.nodo_id, "item": item}


@router.post("/proveedores")
async def create_proveedor(body: ProveedorCreateRequest, _: None = Depends(verify_bearer)):
    rif = _normalize_rif(body.rif_prv)
    cod_prv = rif
    existing = await anyio.to_thread.run_sync(lambda: _get_proveedor(cod_prv))
    if existing is not None:
        raise HTTPException(status_code=409, detail="Provider already exists")
    payload = body.model_dump()
    payload["cod_prv"] = cod_prv
    payload["rif_prv"] = rif
    esp = (payload.get("especial") or "").strip().lower()
    if esp not in ("si", "no"):
        raise HTTPException(status_code=422, detail="Invalid especial")
    payload["especial"] = esp
    if payload.get("email2_prv") == "":
        payload["email2_prv"] = None

    await anyio.to_thread.run_sync(lambda: _upsert_proveedor(ProveedorUpsertRequest(**payload)))
    item = await anyio.to_thread.run_sync(lambda: _get_proveedor(cod_prv))
    return {"nodo_id": settings.nodo_id, "item": item, "message": "ok"}


@router.patch("/proveedores/{cod_prv}")
async def patch_proveedor(
    cod_prv: str,
    body: ProveedorPatchRequest,
    _: None = Depends(verify_bearer),
):
    existing = await anyio.to_thread.run_sync(lambda: _get_proveedor(cod_prv))
    if existing is None:
        raise HTTPException(status_code=404, detail="Provider not found")

    payload = body.model_dump(exclude_unset=True)
    if not payload:
        return {"nodo_id": settings.nodo_id, "item": existing, "message": "ok"}

    merged = dict(existing)
    merged.update(payload)
    merged["cod_prv"] = cod_prv
    merged["rif_prv"] = existing["rif_prv"]
    if "especial" in payload:
        esp = (payload.get("especial") or "").strip().lower()
        if esp not in ("si", "no"):
            raise HTTPException(status_code=422, detail="Invalid especial")
        merged["especial"] = esp
    if merged.get("email2_prv") == "":
        merged["email2_prv"] = None

    await anyio.to_thread.run_sync(lambda: _upsert_proveedor(ProveedorUpsertRequest(**merged)))
    item = await anyio.to_thread.run_sync(lambda: _get_proveedor(cod_prv))
    return {"nodo_id": settings.nodo_id, "item": item, "message": "ok"}
