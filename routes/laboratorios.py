from fastapi import APIRouter, Depends, HTTPException, Query

import anyio

from core.config import settings
from db.general_store import fetch_laboratorio_by_code, fetch_laboratorio_by_name
from db.mysql import MySqlClient
from laboratorios_models import LaboratorioCreateRequest, LaboratorioPatchRequest
from middleware.auth import verify_bearer

router = APIRouter(prefix="/api/laboratorios", tags=["laboratorios"])


def _catalog_like(term: str) -> str:
    return f"%{term.strip()}%"


def _fetch_laboratorios(
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
              AND (%s = '' OR cgeneral LIKE %s OR ngeneral LIKE %s)
              AND (%s = '' OR cgeneral LIKE %s)
              AND (%s = '' OR ngeneral LIKE %s)
        """
        params = (
            q,
            like_search or "",
            like_search or "",
            c,
            like_codigo or "",
            n,
            like_nombre or "",
        )
        cur.execute(f"SELECT COUNT(*) AS cnt FROM general {where}", params)
        total_row = cur.fetchone() or {}
        total = int(total_row.get("cnt") or 0)

        cur.execute(
            f"""
            SELECT cgeneral, ngeneral
            FROM general
            {where}
            ORDER BY ngeneral ASC
            LIMIT %s OFFSET %s
            """,
            (*params, int(limit), offset),
        )
        return list(cur.fetchall() or []), total
    finally:
        conn.close()


def _get_laboratorio(cgeneral: str) -> dict | None:
    mysql = MySqlClient()
    if not mysql.is_configured():
        raise RuntimeError("Node MySQL not configured (set MYSQL_* in env.txt/.env)")

    conn = mysql.connect()
    try:
        cur = conn.cursor(dictionary=True)
        return fetch_laboratorio_by_code(cur, cgeneral)
    finally:
        conn.close()


def _create_laboratorio(body: LaboratorioCreateRequest) -> None:
    mysql = MySqlClient()
    if not mysql.is_configured():
        raise RuntimeError("Node MySQL not configured (set MYSQL_* in env.txt/.env)")

    conn = mysql.connect()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO general (cgeneral, ngeneral)
            VALUES (%s, %s)
            """,
            (body.cgeneral.strip(), body.ngeneral.strip()),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _patch_laboratorio(cgeneral: str, patch: dict) -> int:
    mysql = MySqlClient()
    if not mysql.is_configured():
        raise RuntimeError("Node MySQL not configured (set MYSQL_* in env.txt/.env)")

    sets: list[str] = []
    vals: list[object] = []

    if "ngeneral" in patch and patch["ngeneral"] is not None:
        new_name = str(patch["ngeneral"]).strip()
        sets.append("ngeneral = %s")
        vals.append(new_name)

    if not sets:
        return 1

    conn = mysql.connect()
    try:
        cur = conn.cursor(dictionary=True)
        existing = fetch_laboratorio_by_code(cur, cgeneral)
        if existing is None:
            return 0
        if "ngeneral" in patch and patch["ngeneral"] is not None:
            new_name = str(patch["ngeneral"]).strip()
            old_name = str(existing.get("ngeneral") or "").strip()
            if old_name != new_name:
                conflict = fetch_laboratorio_by_name(cur, new_name)
                if conflict is not None and str(conflict.get("cgeneral")).strip() != cgeneral:
                    raise HTTPException(
                        status_code=409,
                        detail="Laboratory name already exists",
                    )

        cur.execute(
            f"""
            UPDATE general
            SET {", ".join(sets)}
            WHERE cgeneral = %s
            """,
            (*vals, cgeneral),
        )
        updated = int(cur.rowcount or 0)
        conn.commit()
        return updated
    except HTTPException:
        conn.rollback()
        raise
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@router.get("")
async def list_laboratorios(
    search: str = Query("", description="Match code or name"),
    codigo: str = Query("", description="Filter by code (partial)"),
    nombre: str = Query("", description="Filter by name (partial)"),
    page: int = Query(1, ge=1, description="Page"),
    limit: int = Query(25, ge=1, le=500, description="Rows per page"),
    _: None = Depends(verify_bearer),
):
    items, total = await anyio.to_thread.run_sync(
        lambda: _fetch_laboratorios(search, codigo, nombre, page, limit)
    )
    total_pages = 0 if total == 0 else (total + limit - 1) // limit
    return {
        "search": search,
        "codigo": codigo,
        "filtro_nombre": nombre,
        "nodo_id": settings.nodo_id,
        "items": items,
        "page": page,
        "limit": limit,
        "total": total,
        "totalPages": total_pages,
        "message": "ok",
    }


@router.get("/{cgeneral}")
async def get_laboratorio(cgeneral: str, _: None = Depends(verify_bearer)):
    item = await anyio.to_thread.run_sync(lambda: _get_laboratorio(cgeneral))
    if not item:
        raise HTTPException(status_code=404, detail="Laboratory not found")
    return {"nodo_id": settings.nodo_id, "item": item}


@router.post("")
async def create_laboratorio(
    body: LaboratorioCreateRequest,
    _: None = Depends(verify_bearer),
):
    local_item = await anyio.to_thread.run_sync(lambda: _get_laboratorio(body.cgeneral))
    if local_item is not None:
        raise HTTPException(status_code=409, detail="Laboratory already exists")

    def _check_name_and_create() -> None:
        mysql = MySqlClient()
        if not mysql.is_configured():
            raise RuntimeError("Node MySQL not configured (set MYSQL_* in env.txt/.env)")
        conn = mysql.connect()
        try:
            cur = conn.cursor(dictionary=True)
            if fetch_laboratorio_by_name(cur, body.ngeneral) is not None:
                raise HTTPException(
                    status_code=409,
                    detail="Laboratory name already exists",
                )
            _create_laboratorio(body)
        finally:
            conn.close()

    await anyio.to_thread.run_sync(_check_name_and_create)
    item = await anyio.to_thread.run_sync(lambda: _get_laboratorio(body.cgeneral))
    return {"nodo_id": settings.nodo_id, "item": item, "message": "ok"}


@router.patch("/{cgeneral}")
async def patch_laboratorio(
    cgeneral: str,
    body: LaboratorioPatchRequest,
    _: None = Depends(verify_bearer),
):
    local_item = await anyio.to_thread.run_sync(lambda: _get_laboratorio(cgeneral))
    if local_item is None:
        raise HTTPException(status_code=404, detail="Laboratory not found")

    payload = body.model_dump(exclude_unset=True)
    if not payload:
        return {"nodo_id": settings.nodo_id, "item": local_item, "message": "ok"}

    updated = await anyio.to_thread.run_sync(lambda: _patch_laboratorio(cgeneral, payload))
    if updated == 0:
        raise HTTPException(status_code=404, detail="Laboratory not found")

    item = await anyio.to_thread.run_sync(lambda: _get_laboratorio(cgeneral))
    return {"nodo_id": settings.nodo_id, "item": item, "message": "ok"}
