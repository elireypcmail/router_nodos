from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response

import anyio
from pydantic import BaseModel, Field, field_validator, model_validator

from core.config import settings
from db.calternos_store import (
    attach_codigos_alternos_to_items,
    fetch_codigos_alternos,
    insert_codigos_alternos,
    normalize_codigos_alternos,
    replace_codigos_alternos,
)
from db.inventario_identifier_conflict import assert_product_identifiers_available
from db.lotes_store import fetch_lotes_groups, lotes_where
from db.detallepr_store import (
    apply_inventario_create_pricing,
    apply_inventario_pg1_pricing,
    attach_detallepr_divisa_pricing_to_item,
    attach_detallepr_divisa_pricing_to_items,
)
from db.general_store import (
    attach_laboratory_to_items,
    validate_laboratorio_codigo,
)
from db.inventario_catalog_attach import attach_category_provider_to_items
from db.mysql import MySqlClient
from db.price_from_net_apply import PriceFromNetError, apply_price_from_net
from db.product_porvg import validate_porvg
from db.sinv_store import default_fcrea_today, upsert_sinv
from db.sinvimg_store import (
    attach_imagen_flags_to_items,
    attach_imagen_metadata,
    decode_imagen_base64,
    detect_content_type,
    fetch_imagen_bytes,
    upsert_sinvimg,
)
from middleware.auth import verify_bearer

router = APIRouter(prefix="/api", tags=["inventario"])


class InventarioCreateRequest(BaseModel):
    codigo: str = Field(min_length=1, max_length=30, pattern=r"^[A-Za-z0-9]+$")
    descrip: str = Field(min_length=1, max_length=240)
    ccate: str = Field(min_length=1, max_length=10, pattern=r"^\d+$")
    cod_prv: str = Field(min_length=1, max_length=30, pattern=r"^[A-Za-z0-9]+$")
    pg1: float = Field(ge=0, description="% ganancia lista 1 (Bs y divisa); precio1 se deja en 0")
    barra: str = Field(min_length=0, max_length=30)
    referencia: str = Field(min_length=0, max_length=15)
    componente: str = Field(min_length=0, max_length=240)
    stockmin: float = Field(ge=0)
    stockmax: float = Field(ge=0)
    recipe: int = Field(ge=0, le=1)
    cfrio: int = Field(ge=0, le=1)
    activo: int = Field(ge=0, le=1)
    porvg: float | None = Field(
        default=None,
        description="Alícuota IVA: solo 0, 8, 16 o 31",
    )
    existencia: float | None = Field(default=None, ge=0)
    costo: float | None = Field(default=None, ge=0)
    codigos_alternos: list[str] = Field(
        default_factory=list,
        description="Códigos alternos (barra/EAN); se guardan en calternos con cpadre=codigo",
    )
    imagen_base64: str | None = Field(
        default=None,
        description="Imagen JPEG/PNG/GIF/WebP en base64 (opcional; acepta data URL)",
    )
    laboratorio_codigo: str | None = Field(
        default=None,
        min_length=1,
        max_length=10,
        pattern=r"^\d+$",
        description="Código cgeneral en tabla general; se guarda en sinv.cgeneral",
    )

    @field_validator("porvg")
    @classmethod
    def _validate_porvg(cls, value: float | None) -> float | None:
        return validate_porvg(value)

    @field_validator("codigos_alternos")
    @classmethod
    def _validate_codigos_alternos(cls, value: list[str]) -> list[str]:
        try:
            return normalize_codigos_alternos(value)
        except ValueError as exc:
            raise ValueError(str(exc)) from exc


class InventarioPatchRequest(BaseModel):
    descrip: str | None = Field(default=None, min_length=1, max_length=240)
    ccate: str | None = Field(
        default=None, min_length=1, max_length=10, pattern=r"^\d+$"
    )
    cod_prv: str | None = Field(
        default=None, min_length=1, max_length=30, pattern=r"^[A-Za-z0-9]+$"
    )
    pg1: float | None = Field(
        default=None, ge=0, description="% ganancia lista 1; recalcula precio1..4"
    )
    barra: str | None = Field(default=None, min_length=0, max_length=30)
    referencia: str | None = Field(default=None, min_length=0, max_length=15)
    componente: str | None = Field(default=None, min_length=0, max_length=240)
    stockmin: float | None = Field(default=None, ge=0)
    stockmax: float | None = Field(default=None, ge=0)
    recipe: int | None = Field(default=None, ge=0, le=1)
    cfrio: int | None = Field(default=None, ge=0, le=1)
    activo: int | None = Field(default=None, ge=0, le=1)
    porvg: float | None = Field(default=None, ge=0)
    imagen_base64: str | None = Field(
        default=None,
        description="Imagen JPEG/PNG/GIF/WebP en base64 (opcional; reemplaza la existente)",
    )
    codigos_alternos: list[str] | None = Field(
        default=None,
        description="Códigos alternos; reemplaza la lista completa si se envía",
    )
    laboratorio_codigo: str | None = Field(
        default=None,
        max_length=10,
        description="Código cgeneral; vacío para quitar laboratorio",
    )

    @field_validator("codigos_alternos")
    @classmethod
    def _validate_patch_codigos_alternos(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        try:
            return normalize_codigos_alternos(value)
        except ValueError as exc:
            raise ValueError(str(exc)) from exc


class PrecioDesdeNetoRequest(BaseModel):
    precio_sin_iva_usd: float | None = Field(
        default=None,
        gt=0,
        description="Precio sin IVA en USD",
    )
    precio_con_iva_usd: float | None = Field(
        default=None,
        gt=0,
        description="Precio con IVA en USD (alternativa a precio_sin_iva_usd)",
    )
    tasa: float | None = Field(
        default=None,
        gt=0,
        description="Tasa BCV del día (requerida si se envía precio USD)",
    )
    porvg: float | None = Field(
        default=None,
        description="Alícuota IVA: 0, 8, 16 o 31 (opcional)",
    )

    @field_validator("porvg")
    @classmethod
    def _validate_porvg_field(cls, value: float | None) -> float | None:
        return validate_porvg(value)

    @model_validator(mode="after")
    def _validate_request_shape(self) -> "PrecioDesdeNetoRequest":
        if (
            self.precio_sin_iva_usd is not None
            and self.precio_con_iva_usd is not None
        ):
            raise ValueError(
                "precio_sin_iva_usd and precio_con_iva_usd are mutually exclusive"
            )
        if (
            self.precio_sin_iva_usd is None
            and self.precio_con_iva_usd is None
            and self.porvg is None
        ):
            raise ValueError(
                "precio_sin_iva_usd, precio_con_iva_usd or porvg is required"
            )
        if (
            self.precio_sin_iva_usd is not None or self.precio_con_iva_usd is not None
        ) and self.tasa is None:
            raise ValueError("tasa is required when a USD price is sent")
        return self


class PrecioLoteItemRequest(BaseModel):
    codigo: str = Field(min_length=1, max_length=30)
    precio_con_iva_usd: float = Field(gt=0, description="Precio lista 1 con IVA en USD")


class PrecioLoteRequest(BaseModel):
    tasa: float = Field(gt=0, description="Tasa BCV del día (global al lote)")
    items: list[PrecioLoteItemRequest] = Field(min_length=1, max_length=100)


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
    porvg: float | None = None
    existencia: float | None = None
    costo: float | None = None


def _fk_exists(cur, table: str, col: str, value: str) -> bool:
    cur.execute(f"SELECT 1 FROM {table} WHERE {col} = %s LIMIT 1", (value,))
    return cur.fetchone() is not None


def _set_sinv_laboratorio(cur, codigo: str, laboratorio_codigo: str | None) -> None:
    if laboratorio_codigo is None:
        return
    code = str(laboratorio_codigo).strip()
    if not code:
        stored = ""
    else:
        try:
            stored = validate_laboratorio_codigo(cur, code)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="Invalid laboratorio_codigo") from exc
    cur.execute(
        "UPDATE sinv SET cgeneral = %s WHERE codigo = %s",
        (stored, codigo),
    )


def _catalog_like(term: str) -> str:
    return f"%{term.strip()}%"


def _fetch_inventario(
    search: str,
    codigo: str,
    nombre: str,
    page: int,
    limit: int,
    *,
    con_existencia: bool | None = None,
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
              AND (%s = '' OR codigo LIKE %s OR descrip LIKE %s OR barra LIKE %s)
              AND (%s = '' OR codigo LIKE %s)
              AND (%s = '' OR descrip LIKE %s)
        """
        params: list[object] = [
            q,
            like_search or "",
            like_search or "",
            like_search or "",
            c,
            like_codigo or "",
            n,
            like_nombre or "",
        ]
        if con_existencia is True:
            where += " AND COALESCE(existencia, 0) > 0"
            order_by = "ORDER BY existencia DESC, descrip ASC"
        elif con_existencia is False:
            where += " AND COALESCE(existencia, 0) <= 0"
            order_by = "ORDER BY descrip ASC"
        else:
            order_by = "ORDER BY descrip ASC"

        cur.execute(f"SELECT COUNT(*) AS cnt FROM sinv {where}", tuple(params))
        total_row = cur.fetchone() or {}
        total = int(total_row.get("cnt") or 0)

        cur.execute(
            f"""
            SELECT
              codigo,
              descrip,
              ccate,
              cod_prv,
              cgeneral,
              precio1,
              pg1,
              porvg,
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
              costopro
            FROM sinv
            {where}
            {order_by}
            LIMIT %s OFFSET %s
            """,
            (*params, int(limit), int(offset)),
        )
        rows = cur.fetchall() or []
        attach_codigos_alternos_to_items(cur, rows)
        attach_imagen_flags_to_items(cur, rows)
        attach_detallepr_divisa_pricing_to_items(cur, rows)
        attach_category_provider_to_items(cur, rows)
        attach_laboratory_to_items(cur, rows)
        return list(rows), total
    finally:
        conn.close()


_PRICING_KEYS = (
    "codigo",
    "existencia",
    "precio1",
    "pg1",
    "costo",
    "costopro",
    "precio1div",
    "pg1div",
    "costodiv",
    "costoprodiv",
)


def _project_pricing_row(row: dict) -> dict:
    return {k: row.get(k, 0 if k != "codigo" else "") for k in _PRICING_KEYS}


def _fetch_inventario_pricing(
    search: str,
    codigo: str,
    nombre: str,
    page: int,
    limit: int,
    *,
    con_existencia: bool | None = None,
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
              AND (%s = '' OR codigo LIKE %s OR descrip LIKE %s OR barra LIKE %s)
              AND (%s = '' OR codigo LIKE %s)
              AND (%s = '' OR descrip LIKE %s)
        """
        params: list[object] = [
            q,
            like_search or "",
            like_search or "",
            like_search or "",
            c,
            like_codigo or "",
            n,
            like_nombre or "",
        ]
        if con_existencia is True:
            where += " AND COALESCE(existencia, 0) > 0"
            order_by = "ORDER BY existencia DESC, codigo ASC"
        elif con_existencia is False:
            where += " AND COALESCE(existencia, 0) <= 0"
            order_by = "ORDER BY codigo ASC"
        else:
            order_by = "ORDER BY codigo ASC"

        cur.execute(f"SELECT COUNT(*) AS cnt FROM sinv {where}", tuple(params))
        total_row = cur.fetchone() or {}
        total = int(total_row.get("cnt") or 0)

        cur.execute(
            f"""
            SELECT
              codigo,
              existencia,
              precio1,
              pg1,
              costo,
              costopro
            FROM sinv
            {where}
            {order_by}
            LIMIT %s OFFSET %s
            """,
            (*params, int(limit), int(offset)),
        )
        rows = list(cur.fetchall() or [])
        attach_detallepr_divisa_pricing_to_items(cur, rows)
        return [_project_pricing_row(row) for row in rows], total
    finally:
        conn.close()


def _get_item_pricing(codigo: str) -> dict | None:
    mysql = MySqlClient()
    if not mysql.is_configured():
        raise RuntimeError("Node MySQL not configured (set MYSQL_* in env.txt/.env)")

    key = (codigo or "").strip()
    if not key:
        return None

    conn = mysql.connect()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            """
            SELECT
              codigo,
              existencia,
              precio1,
              pg1,
              costo,
              costopro
            FROM sinv
            WHERE codigo = %s
            LIMIT 1
            """,
            (key,),
        )
        row = cur.fetchone()
        if not row:
            return None
        attach_detallepr_divisa_pricing_to_item(cur, row)
        return _project_pricing_row(row)
    finally:
        conn.close()


def _get_item(codigo: str) -> dict | None:
    mysql = MySqlClient()
    if not mysql.is_configured():
        raise RuntimeError("Node MySQL not configured (set MYSQL_* in env.txt/.env)")

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
              cgeneral,
              precio1,
              pg1,
              porvg,
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
              fultimav,
              fultimac
            FROM sinv
            WHERE codigo = %s
            LIMIT 1
            """,
            (codigo,),
        )
        row = cur.fetchone()
        if row:
            row["codigos_alternos"] = fetch_codigos_alternos(cur, codigo)
            # Solo flag; el binario va por GET /inventario/{codigo}/imagen
            attach_imagen_metadata(cur, row, include_payload=False)
            attach_detallepr_divisa_pricing_to_item(cur, row)
            attach_category_provider_to_items(cur, [row])
            attach_laboratory_to_items(cur, [row])
        return row
    finally:
        conn.close()


def _fetch_lotes(codigo: str) -> list[dict]:
    mysql = MySqlClient()
    if not mysql.is_configured():
        raise RuntimeError("Node MySQL not configured (set MYSQL_* in env.txt/.env)")

    where_sql, params = lotes_where(codigo)
    conn = mysql.connect()
    try:
        cur = conn.cursor(dictionary=True)
        return fetch_lotes_groups(cur, where_sql, params)
    finally:
        conn.close()


def _fetch_imagen_binary(codigo: str) -> tuple[bytes, str] | None:
    mysql = MySqlClient()
    if not mysql.is_configured():
        raise RuntimeError("Node MySQL not configured (set MYSQL_* in env.txt/.env)")

    conn = mysql.connect()
    try:
        cur = conn.cursor()
        data = fetch_imagen_bytes(cur, codigo)
        if not data:
            return None
        return data, detect_content_type(data)
    finally:
        conn.close()


def _save_imagen_from_base64(
    cur,
    codigo: str,
    imagen_base64: str | None,
    *,
    descrip: str,
    ccate: str,
) -> None:
    if not imagen_base64:
        return
    try:
        imagen = decode_imagen_base64(imagen_base64)
        upsert_sinvimg(cur, codigo, imagen, descrip=descrip, ccate=ccate)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


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
        raise RuntimeError("Node MySQL not configured (set MYSQL_* in env.txt/.env)")

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


@router.get("/inventario")
async def inventario(
    search: str = Query("", description="Match code or description"),
    codigo: str = Query("", description="Filter by code (partial)"),
    nombre: str = Query("", description="Filter by description (partial)"),
    con_existencia: bool | None = Query(
        None,
        description="true = solo con stock (>0); false = solo sin stock; omitir = todos",
    ),
    page: int = Query(1, ge=1, description="Page"),
    limit: int = Query(25, ge=1, le=500, description="Rows per page"),
    _: None = Depends(verify_bearer),
):
    items, total = await anyio.to_thread.run_sync(
        lambda: _fetch_inventario(
            search,
            codigo,
            nombre,
            page,
            limit,
            con_existencia=con_existencia,
        )
    )
    total_pages = 0 if total == 0 else (total + limit - 1) // limit
    return {
        "search": search,
        "codigo": codigo,
        "filtro_nombre": nombre,
        "con_existencia": con_existencia,
        "nodo_id": settings.nodo_id,
        "nombre": settings.nodo_nombre,
        "items": items,
        "page": page,
        "limit": limit,
        "total": total,
        "totalPages": total_pages,
        "message": "ok",
    }


@router.get("/inventario/pricing")
async def list_inventario_pricing(
    search: str = Query("", description="Match code, description or barcode"),
    codigo: str = Query("", description="Filter by code (partial)"),
    nombre: str = Query("", description="Filter by description (partial)"),
    con_existencia: bool | None = Query(
        None,
        description="true = solo con stock (>0); false = solo sin stock; omitir = todos",
    ),
    page: int = Query(1, ge=1, description="Page"),
    limit: int = Query(25, ge=1, le=500, description="Rows per page"),
    _: None = Depends(verify_bearer),
):
    items, total = await anyio.to_thread.run_sync(
        lambda: _fetch_inventario_pricing(
            search,
            codigo,
            nombre,
            page,
            limit,
            con_existencia=con_existencia,
        )
    )
    total_pages = 0 if total == 0 else (total + limit - 1) // limit
    return {
        "search": search,
        "codigo": codigo,
        "filtro_nombre": nombre,
        "con_existencia": con_existencia,
        "nodo_id": settings.nodo_id,
        "nombre": settings.nodo_nombre,
        "items": items,
        "page": page,
        "limit": limit,
        "total": total,
        "totalPages": total_pages,
        "message": "ok",
    }


@router.get("/inventario/{codigo}/pricing")
async def get_inventario_pricing(codigo: str, _: None = Depends(verify_bearer)):
    item = await anyio.to_thread.run_sync(lambda: _get_item_pricing(codigo))
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")
    return {"nodo_id": settings.nodo_id, "item": item, "message": "ok"}


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


@router.get("/inventario/{codigo}/imagen")
async def get_inventario_imagen(codigo: str, _: None = Depends(verify_bearer)):
    payload = await anyio.to_thread.run_sync(lambda: _fetch_imagen_binary(codigo))
    if not payload:
        raise HTTPException(status_code=404, detail="Image not found")
    data, content_type = payload
    return Response(content=data, media_type=content_type)


@router.get("/inventario/{codigo}")
async def get_inventario_item(codigo: str, _: None = Depends(verify_bearer)):
    def _fetch() -> dict | None:
        item = _get_item(codigo)
        if not item:
            return None
        try:
            lotes = _fetch_lotes(codigo)
        except Exception:
            lotes = []
        return {"item": item, "lotes": lotes}

    payload = await anyio.to_thread.run_sync(_fetch)
    if not payload:
        raise HTTPException(status_code=404, detail="Item not found")
    return {"nodo_id": settings.nodo_id, **payload}


@router.post("/inventario")
async def create_inventario_item(body: InventarioCreateRequest, _: None = Depends(verify_bearer)):
    existing = await anyio.to_thread.run_sync(lambda: _get_item(body.codigo))
    if existing is not None:
        raise HTTPException(status_code=409, detail="Item already exists")

    def _create_with_fk_check() -> None:
        mysql = MySqlClient()
        if not mysql.is_configured():
            raise RuntimeError("Node MySQL not configured (set MYSQL_* in env.txt/.env)")
        conn = mysql.connect()
        try:
            cur = conn.cursor()
            if not _fk_exists(cur, "catego", "ccate", body.ccate):
                raise HTTPException(status_code=422, detail="Invalid ccate")
            if not _fk_exists(cur, "sprv", "cod_prv", body.cod_prv):
                raise HTTPException(status_code=422, detail="Invalid cod_prv")
            payload = body.model_dump(exclude_unset=True)
            had_laboratorio = "laboratorio_codigo" in payload
            codigos_alternos = payload.pop("codigos_alternos", []) or []
            imagen_base64 = payload.pop("imagen_base64", None)
            laboratorio_codigo = payload.pop("laboratorio_codigo", None)
            payload["precio1"] = 0
            payload["fcrea"] = default_fcrea_today()
            if payload.get("existencia") and not payload.get("costo"):
                raise HTTPException(status_code=422, detail="costo required when existencia > 0")
            try:
                assert_product_identifiers_available(
                    cur,
                    body.codigo,
                    body.barra,
                    codigos_alternos,
                    exclude_codigo=body.codigo,
                )
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            upsert_sinv(cur, payload, patch_keys=set(payload.keys()))
            apply_inventario_create_pricing(cur, body.codigo, body.pg1)
            if codigos_alternos:
                try:
                    insert_codigos_alternos(cur, body.codigo, codigos_alternos)
                except ValueError as exc:
                    raise HTTPException(status_code=422, detail=str(exc)) from exc
            _save_imagen_from_base64(
                cur,
                body.codigo,
                imagen_base64,
                descrip=body.descrip,
                ccate=body.ccate,
            )
            if had_laboratorio:
                _set_sinv_laboratorio(cur, body.codigo, laboratorio_codigo)
            conn.commit()
        except HTTPException:
            conn.rollback()
            raise
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    await anyio.to_thread.run_sync(_create_with_fk_check)
    item = await anyio.to_thread.run_sync(lambda: _get_item(body.codigo))
    return {"nodo_id": settings.nodo_id, "item": item, "message": "ok"}


@router.patch("/inventario/precios")
async def patch_inventario_precios_lote(
    body: PrecioLoteRequest,
    _: None = Depends(verify_bearer),
):
    def _apply_lote() -> dict:
        mysql = MySqlClient()
        if not mysql.is_configured():
            raise RuntimeError("Node MySQL not configured (set MYSQL_* in env.txt/.env)")
        conn = mysql.connect()
        results: list[dict] = []
        updated = 0
        failed = 0
        try:
            cur = conn.cursor()
            for item in body.items:
                sku = item.codigo.strip()
                try:
                    payload = apply_price_from_net(
                        cur,
                        sku,
                        price_inc_tax_usd=item.precio_con_iva_usd,
                        exchange_rate=body.tasa,
                    )
                    results.append(
                        {
                            "codigo": sku,
                            "ok": True,
                            "precio_sin_iva_bs": payload["precio_sin_iva_bs"],
                            "precio_sin_iva_usd": payload["precio_sin_iva_usd"],
                            "precio_con_iva_bs": payload["precio_con_iva_bs"],
                            "precio_con_iva_usd": payload["precio_con_iva_usd"],
                            "pg_bs": payload["pg_bs"],
                            "pg_usd": payload["pg_usd"],
                        }
                    )
                    updated += 1
                except PriceFromNetError as exc:
                    results.append(
                        {
                            "codigo": sku,
                            "ok": False,
                            "error": exc.message,
                        }
                    )
                    failed += 1
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        return {
            "tasa": body.tasa,
            "updated": updated,
            "failed": failed,
            "results": results,
        }

    data = await anyio.to_thread.run_sync(_apply_lote)
    return {
        "nodo_id": settings.nodo_id,
        "nombre": settings.nodo_nombre,
        **data,
        "message": "ok",
    }


@router.patch("/inventario/{codigo}")
async def patch_inventario_item(
    codigo: str,
    body: InventarioPatchRequest,
    _: None = Depends(verify_bearer),
):
    existing = await anyio.to_thread.run_sync(lambda: _get_item(codigo))
    if existing is None:
        raise HTTPException(status_code=404, detail="Item not found")

    def _patch_with_fk_check() -> None:
        mysql = MySqlClient()
        if not mysql.is_configured():
            raise RuntimeError("Node MySQL not configured (set MYSQL_* in env.txt/.env)")
        conn = mysql.connect()
        try:
            cur = conn.cursor()
            payload = body.model_dump(exclude_unset=True)
            if not payload:
                return

            had_laboratorio = "laboratorio_codigo" in payload
            laboratorio_codigo = payload.pop("laboratorio_codigo", None)
            had_alternos = "codigos_alternos" in payload
            codigos_alternos = payload.pop("codigos_alternos", None)

            ccate = payload.get("ccate")
            if ccate is not None and not _fk_exists(cur, "catego", "ccate", ccate):
                raise HTTPException(status_code=422, detail="Invalid ccate")
            cod_prv = payload.get("cod_prv")
            if cod_prv is not None and not _fk_exists(cur, "sprv", "cod_prv", cod_prv):
                raise HTTPException(status_code=422, detail="Invalid cod_prv")

            if "barra" in payload or had_alternos:
                barra_for_check = (
                    payload["barra"] if "barra" in payload else existing.get("barra")
                )
                alternos_for_check = (
                    codigos_alternos
                    if had_alternos
                    else fetch_codigos_alternos(cur, codigo)
                )
                try:
                    assert_product_identifiers_available(
                        cur,
                        codigo,
                        barra_for_check,
                        alternos_for_check,
                        exclude_codigo=codigo,
                    )
                except ValueError as exc:
                    raise HTTPException(status_code=422, detail=str(exc)) from exc

            had_imagen = "imagen_base64" in payload
            imagen_base64 = None
            pg1 = payload.pop("pg1", None)
            payload.pop("precio1", None)
            if had_imagen:
                imagen_base64 = payload.pop("imagen_base64", None)
            payload["codigo"] = codigo
            if payload.keys() - {"codigo"}:
                upsert_sinv(cur, payload, patch_keys=set(payload.keys()))
            if pg1 is not None:
                apply_inventario_pg1_pricing(cur, codigo, pg1)
            if had_imagen:
                _save_imagen_from_base64(
                    cur,
                    codigo,
                    imagen_base64,
                    descrip=str(payload.get("descrip") or existing.get("descrip") or ""),
                    ccate=str(payload.get("ccate") or existing.get("ccate") or ""),
                )
            if had_laboratorio:
                _set_sinv_laboratorio(cur, codigo, laboratorio_codigo)
            if had_alternos:
                try:
                    replace_codigos_alternos(cur, codigo, codigos_alternos or [])
                except ValueError as exc:
                    raise HTTPException(status_code=422, detail=str(exc)) from exc
            conn.commit()
        except HTTPException:
            conn.rollback()
            raise
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    await anyio.to_thread.run_sync(_patch_with_fk_check)
    item = await anyio.to_thread.run_sync(lambda: _get_item(codigo))
    return {"nodo_id": settings.nodo_id, "item": item, "message": "ok"}


@router.post("/inventario/{codigo}/precio-desde-neto")
async def post_precio_desde_neto(
    codigo: str,
    body: PrecioDesdeNetoRequest,
    _: None = Depends(verify_bearer),
):
    def _apply() -> dict:
        mysql = MySqlClient()
        if not mysql.is_configured():
            raise RuntimeError("Node MySQL not configured (set MYSQL_* in env.txt/.env)")
        conn = mysql.connect()
        try:
            cur = conn.cursor()
            try:
                result = apply_price_from_net(
                    cur,
                    codigo,
                    price_ex_tax_usd=body.precio_sin_iva_usd,
                    price_inc_tax_usd=body.precio_con_iva_usd,
                    exchange_rate=body.tasa,
                    porvg=body.porvg,
                )
            except PriceFromNetError as exc:
                raise HTTPException(
                    status_code=exc.status_code,
                    detail=exc.message,
                ) from exc
            conn.commit()
            return result
        except HTTPException:
            conn.rollback()
            raise
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    data = await anyio.to_thread.run_sync(_apply)
    return {
        "nodo_id": settings.nodo_id,
        "nombre": settings.nodo_nombre,
        "codigo": codigo.strip(),
        **data,
        "message": "ok",
    }
