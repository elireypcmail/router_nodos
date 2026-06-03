from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse

import anyio
import uuid
from pydantic import BaseModel, ConfigDict, Field

from core.categoria_trace import is_categoria_entity, trace, trace_exc, trace_warn
from core.config import settings
from db.mysql import MySqlClient
from hub.client import HubClient
from middleware.auth import verify_bearer
from catalog.apply import (
    apply_categoria_row,
    apply_inventario_row,
    apply_inventario_dependency_rows,
    apply_proveedor_row,
    assert_inventario_dependencies,
)
from sync.apply_trace import (
    log_apply_exception,
    log_apply_ok,
    log_apply_start,
    log_apply_value_error,
)
from catalog.pull.inventory_deps import (
    apply_inventory_row_dependencies,
    fetch_row_dependencies_from_hub,
)
from catalog.pull_common import fetch_codes_existing
from db.sinv_price_from_cost import (
    SINV_COST_PRICE_FETCH,
    apply_sinv_cost_and_prices,
)
from db.sinv_store import delete_sinv, prepare_sinv_upsert, upsert_sinv
from db.sprv_store import delete_sprv, upsert_sprv
from sync.models import SyncApplyRequest
from sync.store import SyncEvent

router = APIRouter(prefix="/api/sync", tags=["sync"])


def _mysql_decimal(value) -> float | None:
    if value is None:
        return None
    return float(value)


class SyncEventBody(BaseModel):
    entity_type: str = Field(..., description="Ej. inventory_category, provider")
    payload: dict = Field(default_factory=dict)


def get_sync_store():
    from main import sync_store

    if not sync_store:
        raise RuntimeError("sync_store not initialized")
    return sync_store


def get_outbox_repo():
    from main import outbox_repo

    if not outbox_repo:
        raise RuntimeError("outbox_repo not initialized")
    return outbox_repo


@router.post("/apply")
async def sync_apply(
    body: SyncApplyRequest,
    _: None = Depends(verify_bearer),
):
    if is_categoria_entity(body.entity):
        trace(
            "sync.apply.enqueue",
            event_id=body.event_id,
            entity=body.entity,
            action=body.action,
            sequence=body.sequence,
        )
    store = get_sync_store()
    enqueued = await store.enqueue(
        SyncEvent(
            event_id=body.event_id,
            entity=body.entity,
            action=body.action,
            payload=body.payload,
            sequence=body.sequence,
            created_at=body.created_at,
        )
    )
    return {
        "ok": True,
        "enqueued": enqueued,
        "message": "enqueued" if enqueued else "duplicate_event",
        "event_id": body.event_id,
        "sequence": body.sequence,
    }


@router.post("/events")
async def sync_events(body: SyncEventBody, _: None = Depends(verify_bearer)):
    """Contrato guía (multishop-hub): hub empuja eventos genéricos al nodo."""
    entity = body.entity_type.strip().lower()
    if is_categoria_entity(entity):
        trace("sync.events.start", entity_type=body.entity_type)

    mysql = MySqlClient()
    if not mysql.is_configured():
        if is_categoria_entity(entity):
            trace_warn("sync.events.mysql_not_configured", entity_type=body.entity_type)
        raise RuntimeError("Node MySQL not configured (set MYSQL_* in .env)")

    payload = body.payload or {}

    if entity in {"inventory_category", "categorias", "categoria"}:
        ccate = str(payload.get("ccate") or "").strip()
        ncate = str(payload.get("ncate") or "").strip()
        pganancia = _mysql_decimal(payload.get("pganancia"))
        pdescu = _mysql_decimal(payload.get("pdescu"))
        trace(
            "sync.events.categoria.payload",
            ccate=ccate,
            ncate=ncate,
            pganancia=pganancia,
            pdescu=pdescu,
        )
        if not ccate or not ncate:
            trace_warn("sync.events.categoria.validation_failed", payload_keys=list(payload.keys()))
            raise HTTPException(status_code=422, detail="category requires ccate and ncate")

        def upsert():
            trace("sync.events.categoria.mysql.start", ccate=ccate)
            conn = mysql.connect()
            try:
                cur = conn.cursor()
                cur.execute(
                    """
                    INSERT INTO catego (ccate, ncate, pganancia, pdescu)
                    VALUES (%s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                      ncate = VALUES(ncate),
                      pganancia = VALUES(pganancia),
                      pdescu = VALUES(pdescu)
                    """,
                    (
                        ccate,
                        ncate,
                        pganancia,
                        pdescu,
                    ),
                )
                conn.commit()
                trace("sync.events.categoria.mysql.done", ccate=ccate)
            except Exception as exc:
                conn.rollback()
                trace_exc("sync.events.categoria.mysql.failed", exc, ccate=ccate)
                raise
            finally:
                conn.close()

        trace("sync.events.categoria.thread_pool.before", ccate=ccate)
        await anyio.to_thread.run_sync(upsert)
        trace("sync.events.categoria.done", ccate=ccate)
        return {"received": True, "entity_type": body.entity_type, "message": "ok"}

    if entity in {"proveedores", "proveedor", "provider", "sprv"}:
        action = str(payload.get("action") or "upsert").strip().lower()
        row = payload.get("row")
        if row is None:
            row = payload
        if not isinstance(row, dict):
            raise HTTPException(status_code=422, detail="payload.row must be an object")

        def apply_row():
            conn = mysql.connect()
            try:
                cur = conn.cursor()
                if action == "delete":
                    cod_prv = str(row.get("cod_prv") or "").strip()
                    if not cod_prv:
                        raise RuntimeError("provider row requires cod_prv")
                    delete_sprv(cur, cod_prv)
                else:
                    upsert_sprv(cur, row)
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

        await anyio.to_thread.run_sync(apply_row)
        return {"received": True, "entity_type": body.entity_type, "message": "ok"}

    if entity in {"inventario", "inventory", "sinv"}:
        action = str(payload.get("action") or "upsert").strip().lower()
        row = payload.get("row")
        if row is None:
            row = payload
        if not isinstance(row, dict):
            raise HTTPException(status_code=422, detail="payload.row must be an object")

        hub_catego: dict = {}
        hub_prv: dict = {}
        if action != "delete" and settings.hub_base_url.strip():
            hub = HubClient()
            hub_catego, hub_prv = await fetch_row_dependencies_from_hub(
                hub, mysql, row
            )

        def apply_row():
            conn = mysql.connect()
            try:
                cur = conn.cursor()
                if action == "delete":
                    codigo = str(row.get("codigo") or "").strip()
                    if not codigo:
                        raise RuntimeError("inventory row requires codigo")
                    delete_sinv(cur, codigo)
                else:
                    if hub_catego or hub_prv:
                        ccate = str(row.get("ccate") or "").strip()
                        cod_prv = str(row.get("cod_prv") or "").strip()
                        local_ccates = fetch_codes_existing(
                            mysql, "catego", "ccate", [ccate] if ccate else []
                        )
                        local_prv = fetch_codes_existing(
                            mysql, "sprv", "cod_prv", [cod_prv] if cod_prv else []
                        )
                        apply_inventory_row_dependencies(
                            cur,
                            row,
                            hub_catego=hub_catego,
                            hub_prv=hub_prv,
                            local_ccates=local_ccates,
                            local_prv=local_prv,
                        )
                    upsert_sinv(cur, row)
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

        await anyio.to_thread.run_sync(apply_row)
        return {"received": True, "entity_type": body.entity_type, "message": "ok"}

    if entity in {"ventas", "ventasd", "kardex", "kardexd", "comprasdbf"}:
        raise HTTPException(
            status_code=400,
            detail="Transactional entities (purchase/sale/kardex) are not applied via push; use POST /api/nodo/events or /api/nodo/events/batch with outbox",
        )

    raise HTTPException(
        status_code=400,
        detail=f"unsupported entity_type: {body.entity_type}",
    )


def _cost_ui_round(amount: float) -> float:
    return round(amount, 2)


def _to_float(value: object) -> float:
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    # pymysql devuelve DECIMAL como decimal.Decimal
    if type(value).__name__ == "Decimal":
        return float(value)
    try:
        return float(str(value).strip())
    except Exception:
        return 0.0


def _fetch_sinv_cost_row(cur, codigo: str) -> dict | None:
    """Busca por código normalizado (TRIM); devuelve fila con codigo real en BD."""
    key = codigo.strip()
    if not key:
        return None
    cols = ", ".join(SINV_COST_PRICE_FETCH)
    cur.execute(
        f"SELECT {cols} FROM sinv WHERE TRIM(codigo) = %s LIMIT 1",
        (key,),
    )
    return cur.fetchone()


@router.post("/cost/propose")
async def sync_cost_propose(body: SyncEventBody, _: None = Depends(verify_bearer)):
    """
    Propuesta de actualización de costo (hub -> nodo).

    No modifica tablas si el CPP propuesto (hub) es menor que sinv.costopro local.
    Si aplica, recalcula precio1..5 con pg1..5 programados (pgN > 0).
    """
    entity = body.entity_type.strip().lower()
    if entity not in {"inventory_cost_update", "cost_update", "inventory_cost"}:
        raise HTTPException(
            status_code=400,
            detail=f"unsupported entity_type: {body.entity_type}",
        )

    payload = body.payload or {}
    codigo = str(payload.get("codigo") or "").strip()
    costo_propuesto = _to_float(payload.get("costo_promedio_ponderado"))
    costo_actual_factura = _to_float(payload.get("costo_actual_factura"))

    if not codigo:
        raise HTTPException(status_code=422, detail="cost/propose requires codigo")

    mysql = MySqlClient()
    if not mysql.is_configured():
        raise RuntimeError("Node MySQL not configured (set MYSQL_* in .env)")

    def decide_and_apply():
        conn = mysql.connect()
        try:
            cur = conn.cursor(dictionary=True)
            row = _fetch_sinv_cost_row(cur, codigo)
            if not row:
                return {
                    "status": "not_found",
                    "codigo": codigo,
                    "message": "sinv no encontrado en esta tienda",
                }

            codigo_db = str(row.get("codigo") or codigo).strip()
            costo_local = _to_float(row.get("costo"))
            costopro_local = _to_float(row.get("costopro"))

            propuesto_ui = _cost_ui_round(costo_propuesto)
            local_cpp_ui = _cost_ui_round(costopro_local)

            if propuesto_ui <= 0:
                return {
                    "status": "skipped",
                    "codigo": codigo_db,
                    "reason": "propuesta_sin_costo_util",
                }

            if local_cpp_ui > 0 and propuesto_ui > 0 and propuesto_ui < local_cpp_ui:
                return {
                    "status": "warning",
                    "codigo": codigo_db,
                    "costo_local": costo_local,
                    "costopro_local": costopro_local,
                    "costo_propuesto": costo_propuesto,
                }

            costoant = costo_local
            nuevo_costo = (
                costo_actual_factura if costo_actual_factura != 0 else costo_propuesto
            )

            precios = apply_sinv_cost_and_prices(
                cur,
                codigo_db,
                row,
                costoant=costoant,
                nuevo_costo=nuevo_costo,
                costopro_nuevo=costo_propuesto,
            )
            conn.commit()

            return {
                "status": "applied",
                "codigo": codigo_db,
                "costo_local": costo_local,
                "costopro_local": costopro_local,
                "costo_propuesto": costo_propuesto,
                "precios_recalculados": precios,
            }
        finally:
            try:
                conn.close()
            except Exception:
                pass

    try:
        return await anyio.to_thread.run_sync(decide_and_apply)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/cost/apply")
async def sync_cost_apply(body: SyncEventBody, _: None = Depends(verify_bearer)):
    """
    Forzar actualización de costo (hub -> nodo).

    Se usa después de que el usuario confirma en el portal.
    Recalcula precio1..5 con pg1..5 programados (pgN > 0).
    """
    entity = body.entity_type.strip().lower()
    if entity not in {"inventory_cost_update", "cost_update", "inventory_cost"}:
        raise HTTPException(
            status_code=400,
            detail=f"unsupported entity_type: {body.entity_type}",
        )

    payload = body.payload or {}
    codigo = str(payload.get("codigo") or "").strip()
    costo_propuesto = _to_float(payload.get("costo_promedio_ponderado"))
    costo_actual_factura = _to_float(payload.get("costo_actual_factura"))

    if not codigo:
        raise HTTPException(status_code=422, detail="cost/apply requires codigo")

    mysql = MySqlClient()
    if not mysql.is_configured():
        raise RuntimeError("Node MySQL not configured (set MYSQL_* in .env)")

    def apply():
        conn = mysql.connect()
        try:
            cur = conn.cursor(dictionary=True)
            row = _fetch_sinv_cost_row(cur, codigo)
            if not row:
                return {
                    "status": "not_found",
                    "codigo": codigo,
                    "message": "sinv no encontrado en esta tienda",
                }

            codigo_db = str(row.get("codigo") or codigo).strip()
            costo_local = _to_float(row.get("costo"))
            nuevo_costo = (
                costo_actual_factura if costo_actual_factura != 0 else costo_propuesto
            )

            precios = apply_sinv_cost_and_prices(
                cur,
                codigo_db,
                row,
                costoant=costo_local,
                nuevo_costo=nuevo_costo,
                costopro_nuevo=costo_propuesto,
            )
            conn.commit()
            return {
                "status": "applied",
                "codigo": codigo_db,
                "costo_local": costo_local,
                "costo_propuesto": costo_propuesto,
                "precios_recalculados": precios,
            }
        finally:
            try:
                conn.close()
            except Exception:
                pass

    try:
        return await anyio.to_thread.run_sync(apply)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/categorias")
async def sync_categorias_legacy(request: Request, _: None = Depends(verify_bearer)):
    """Compatibilidad guía: /api/sync/categorias delega a /api/sync/events."""
    trace("sync.categorias_legacy.start")
    payload = await request.json()
    trace("sync.categorias_legacy.payload", keys=list(payload.keys()) if isinstance(payload, dict) else None)
    result = await sync_events(SyncEventBody(entity_type="inventory_category", payload=payload), _)
    trace("sync.categorias_legacy.done")
    return result


async def _run_category_pull_with_warnings(page_size: int) -> dict:
    from catalog.pull.categoria import run_category_pull_from_hub

    mysql = MySqlClient()
    if not mysql.is_configured():
        raise RuntimeError("Node MySQL not configured (set MYSQL_* in .env)")
    return await run_category_pull_from_hub(
        hub=HubClient(), mysql=mysql, page_size=page_size
    )


async def _run_provider_pull_with_warnings(page_size: int) -> dict:
    from catalog.pull.proveedor import run_provider_pull_from_hub

    mysql = MySqlClient()
    if not mysql.is_configured():
        raise RuntimeError("Node MySQL not configured (set MYSQL_* in .env)")
    return await run_provider_pull_from_hub(
        hub=HubClient(), mysql=mysql, page_size=page_size
    )


@router.post("/categorias/pull")
async def sync_categorias_pull(
    page_size: int = Query(100, ge=1, le=500, description="Hub page size"),
    _: None = Depends(verify_bearer),
):
    trace("sync.pull.start", page_size=page_size, entity="categoria")
    result = await _run_category_pull_with_warnings(page_size)
    trace("sync.pull.done", **{k: result.get(k) for k in ("pulled", "inserted", "conflicts")})
    return result


@router.post("/proveedores/pull")
async def sync_proveedores_pull(
    page_size: int = Query(100, ge=1, le=500),
    _: None = Depends(verify_bearer),
):
    return await _run_provider_pull_with_warnings(page_size)


async def _run_category_push_to_hub() -> dict:
    from catalog.push.categoria import run_category_push_to_hub

    mysql = MySqlClient()
    if not mysql.is_configured():
        raise RuntimeError("Node MySQL not configured (set MYSQL_* in .env)")
    return await run_category_push_to_hub(hub=HubClient(), mysql=mysql)


async def _run_provider_push_to_hub() -> dict:
    from catalog.push.proveedor import run_provider_push_to_hub

    mysql = MySqlClient()
    if not mysql.is_configured():
        raise RuntimeError("Node MySQL not configured (set MYSQL_* in .env)")
    return await run_provider_push_to_hub(hub=HubClient(), mysql=mysql)


async def _run_inventory_push_to_hub() -> dict:
    from catalog.push.inventario import run_inventory_push_to_hub

    mysql = MySqlClient()
    if not mysql.is_configured():
        raise RuntimeError("Node MySQL not configured (set MYSQL_* in .env)")
    return await run_inventory_push_to_hub(hub=HubClient(), mysql=mysql)


async def _run_transaction_push_file_to_hub(
    *,
    mode: str,
    codigo: str | None = None,
    since_watermark=None,
) -> dict:
    from sync.jobs.export_transactions import export_transaction_push_file
    from sync.jobs.files import delete_job_file

    mysql = MySqlClient()
    if not mysql.is_configured():
        raise RuntimeError("Node MySQL not configured (set MYSQL_* in .env)")
    hub = HubClient()
    job_id = f"{mode}-{uuid.uuid4()}"

    path, total, export_meta = await anyio.to_thread.run_sync(
        lambda: export_transaction_push_file(
            job_id=job_id,
            mysql=mysql,
            nodo_id=settings.nodo_id,
            mode=mode,
            codigo=codigo,
            since_watermark=since_watermark,
        )
    )
    try:
        result = await hub.send_ingest_events_from_file(path)
    finally:
        delete_job_file(job_id)
    return {
        "message": "ok",
        "mode": mode,
        "codigo": (codigo or "").strip() or None,
        "job_id": job_id,
        "file_rows": total,
        "hub_result": result,
        "watermark": {
            "since": export_meta.get("since_watermark"),
            "max": export_meta.get("max_watermark"),
        },
    }


async def _run_transaction_push_general_to_hub(
    *,
    codigo: str | None = None,
    since_purchase=None,
    since_sale=None,
) -> dict:
    compras = await _run_transaction_push_file_to_hub(
        mode="purchase",
        codigo=codigo,
        since_watermark=since_purchase,
    )
    ventas = await _run_transaction_push_file_to_hub(
        mode="sale",
        codigo=codigo,
        since_watermark=since_sale,
    )
    return {
        "message": "ok",
        "codigo": (codigo or "").strip() or None,
        "pushes": {
            "compras": compras,
            "ventas": ventas,
        },
        "totals": {
            "file_rows": int(compras.get("file_rows") or 0)
            + int(ventas.get("file_rows") or 0),
            "accepted": int(
                ((compras.get("hub_result") or {}).get("accepted") or 0)
            )
            + int(((ventas.get("hub_result") or {}).get("accepted") or 0)),
            "duplicates": int(
                ((compras.get("hub_result") or {}).get("duplicates") or 0)
            )
            + int(((ventas.get("hub_result") or {}).get("duplicates") or 0)),
            "failed": int(((compras.get("hub_result") or {}).get("failed") or 0))
            + int(((ventas.get("hub_result") or {}).get("failed") or 0)),
            "total": int(((compras.get("hub_result") or {}).get("total") or 0))
            + int(((ventas.get("hub_result") or {}).get("total") or 0)),
        },
    }


@router.post("/categorias/push")
async def sync_categorias_push(_: None = Depends(verify_bearer)):
    trace("sync.push.start", entity="categoria")
    result = await _run_category_push_to_hub()
    trace("sync.push.done", **{k: result.get(k) for k in ("pulled", "inserted", "conflicts")})
    return result


@router.post("/proveedores/push")
async def sync_proveedores_push(_: None = Depends(verify_bearer)):
    trace("sync.push.start", entity="proveedor")
    result = await _run_provider_push_to_hub()
    trace("sync.push.done", **{k: result.get(k) for k in ("pulled", "inserted", "conflicts")})
    return result


@router.post("/inventario/push")
async def sync_inventario_push(_: None = Depends(verify_bearer)):
    trace("sync.push.start", entity="inventario")
    result = await _run_inventory_push_to_hub()
    trace(
        "sync.push.done",
        **{
            k: result.get(k)
            for k in ("pulled", "inserted", "conflicts", "missing_dependencies")
        },
    )
    return result


@router.post("/compras/push-file")
async def sync_compras_push_file(
    codigo: str | None = Query(
        default=None,
        description="Opcional: si se indica, empuja solo compras de ese producto (codigo)",
    ),
    since_fecha: str | None = Query(
        default=None,
        description="Desde hub: exportar kardex con fecha posterior (YYYY-MM-DD)",
    ),
    since_contador: int | None = Query(
        default=None,
        description="Desempate mismo día (contador kardex)",
    ),
    _: None = Depends(verify_bearer),
):
    from sync.jobs.transaction_sync_types import parse_since_query

    since = None if (codigo or "").strip() else parse_since_query(
        since_fecha, since_contador
    )
    return await _run_transaction_push_file_to_hub(
        mode="purchase",
        codigo=codigo,
        since_watermark=since,
    )


@router.post("/ventas/push-file")
async def sync_ventas_push_file(
    codigo: str | None = Query(
        default=None,
        description="Opcional: si se indica, empuja solo ventas de ese producto (codigo)",
    ),
    since_fecha: str | None = Query(
        default=None,
        description="Desde hub: exportar kardex con fecha posterior (YYYY-MM-DD)",
    ),
    since_contador: int | None = Query(
        default=None,
        description="Desempate mismo día (contador kardex)",
    ),
    _: None = Depends(verify_bearer),
):
    from sync.jobs.transaction_sync_types import parse_since_query

    since = None if (codigo or "").strip() else parse_since_query(
        since_fecha, since_contador
    )
    return await _run_transaction_push_file_to_hub(
        mode="sale",
        codigo=codigo,
        since_watermark=since,
    )


@router.post("/transacciones/push-file")
async def sync_transacciones_push_file(
    codigo: str | None = Query(
        default=None,
        description=(
            "Opcional: si se indica, empuja compras y ventas del producto (codigo)"
        ),
    ),
    since_fecha_purchase: str | None = Query(default=None),
    since_contador_purchase: int | None = Query(default=None),
    since_fecha_sale: str | None = Query(default=None),
    since_contador_sale: int | None = Query(default=None),
    _: None = Depends(verify_bearer),
):
    from sync.jobs.transaction_sync_types import parse_since_query

    codigo_clean = (codigo or "").strip()
    since_purchase = None if codigo_clean else parse_since_query(
        since_fecha_purchase, since_contador_purchase
    )
    since_sale = None if codigo_clean else parse_since_query(
        since_fecha_sale, since_contador_sale
    )
    return await _run_transaction_push_general_to_hub(
        codigo=codigo,
        since_purchase=since_purchase,
        since_sale=since_sale,
    )


@router.post("/productos/push")
async def sync_productos_push(_: None = Depends(verify_bearer)):
    """Alias de inventario/push."""
    return await _run_inventory_push_to_hub()


async def _run_inventory_pull_with_warnings(page_size: int) -> dict:
    from catalog.pull.inventario import run_inventory_pull_from_hub

    mysql = MySqlClient()
    if not mysql.is_configured():
        raise RuntimeError("Node MySQL not configured (set MYSQL_* in .env)")
    hub = HubClient()
    return await run_inventory_pull_from_hub(
        hub=hub,
        mysql=mysql,
        page_size=page_size,
    )


@router.post("/productos/pull")
async def sync_productos_pull(
    page_size: int = Query(100, ge=1, le=500),
    _: None = Depends(verify_bearer),
):
    """Pull de catálogo: inserta nuevos; conflictos -> warnings en el hub."""
    return await _run_inventory_pull_with_warnings(page_size)


@router.post("/inventario/pull")
async def sync_inventario_pull(
    page_size: int = Query(100, ge=1, le=500),
    _: None = Depends(verify_bearer),
):
    return await _run_inventory_pull_with_warnings(page_size)


class ApplyFromHubBody(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    row: dict = Field(..., description="Fila del hub")
    require_local_dependencies: bool = Field(
        default=False,
        validation_alias="require_local_dependencies",
        description="If true, require category and provider in MySQL before inventory",
    )
    categoria_row: dict | None = Field(
        default=None,
        validation_alias="categoria_row",
        description="Optional: upsert catego before inventory (same transaction)",
    )
    proveedor_row: dict | None = Field(
        default=None,
        validation_alias="proveedor_row",
        description="Optional: upsert sprv before inventory (same transaction)",
    )


@router.post("/categorias/apply-from-hub")
async def sync_categorias_apply_from_hub(
    body: ApplyFromHubBody,
    _: None = Depends(verify_bearer),
):
    return await _apply_from_hub(body, apply_categoria_row, code_field="ccate")


@router.post("/proveedores/apply-from-hub")
async def sync_proveedores_apply_from_hub(
    body: ApplyFromHubBody,
    _: None = Depends(verify_bearer),
):
    return await _apply_from_hub(body, apply_proveedor_row, code_field="cod_prv")


@router.post("/inventario/apply-from-hub")
async def sync_inventario_apply_from_hub(
    body: ApplyFromHubBody,
    _: None = Depends(verify_bearer),
):
    mysql = MySqlClient()
    if not mysql.is_configured():
        raise RuntimeError("Node MySQL not configured (set MYSQL_* in .env)")
    row = body.row
    if not isinstance(row, dict):
        raise HTTPException(status_code=422, detail="row must be an object")

    entity = "inventario"

    def apply():
        log_apply_start(
            entity,
            require_local_dependencies=body.require_local_dependencies,
            row=row,
        )
        conn = mysql.connect()
        try:
            cur = conn.cursor()
            apply_inventario_dependency_rows(
                cur,
                categoria_row=body.categoria_row,
                proveedor_row=body.proveedor_row,
            )
            if body.require_local_dependencies:
                assert_inventario_dependencies(cur, row)
            apply_inventario_row(cur, row)
            conn.commit()
        except ValueError as exc:
            conn.rollback()
            log_apply_value_error(
                entity,
                str(exc),
                require_local_dependencies=body.require_local_dependencies,
                row=row,
            )
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            conn.rollback()
            log_apply_exception(
                entity,
                exc,
                require_local_dependencies=body.require_local_dependencies,
                row=row,
            )
            raise
        finally:
            conn.close()

    await anyio.to_thread.run_sync(apply)
    codigo = str(row.get("codigo") or "").strip()
    log_apply_ok(entity, code=codigo)
    return {"applied": True, "codigo": codigo, "message": "ok"}


async def _apply_from_hub(
    body: ApplyFromHubBody,
    apply_fn,
    *,
    code_field: str,
) -> dict:
    mysql = MySqlClient()
    if not mysql.is_configured():
        raise RuntimeError("Node MySQL not configured (set MYSQL_* in .env)")
    row = body.row
    if not isinstance(row, dict):
        raise HTTPException(status_code=422, detail="row must be an object")

    entity = code_field

    def apply():
        log_apply_start(entity, row=row)
        conn = mysql.connect()
        try:
            cur = conn.cursor()
            apply_fn(cur, row)
            conn.commit()
        except ValueError as exc:
            conn.rollback()
            log_apply_value_error(entity, str(exc), row=row)
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            conn.rollback()
            log_apply_exception(entity, exc, row=row)
            raise
        finally:
            conn.close()

    await anyio.to_thread.run_sync(apply)
    code = str(row.get(code_field) or "").strip()
    log_apply_ok(entity, code=code)
    return {"applied": True, "codigo": code, "message": "ok"}


@router.post("/backfill-inicial")
async def sync_backfill_inicial(
    page_size: int = Query(100, ge=1, le=500),
    _: None = Depends(verify_bearer),
):
    """Orden recomendado: categorías -> proveedores -> inventario (artículos)."""
    cat = await _run_category_pull_with_warnings(page_size)
    prv = await _run_provider_pull_with_warnings(page_size)
    inv = await _run_inventory_pull_with_warnings(page_size)
    return {
        "message": "ok",
        "page_size": page_size,
        "categorias": cat,
        "proveedores": prv,
        "inventario": inv,
    }


@router.post("/push-inicial")
async def sync_push_inicial(_: None = Depends(verify_bearer)):
    """Sube categorías, proveedores e inventario de la tienda al hub."""
    cat = await _run_category_push_to_hub()
    prv = await _run_provider_push_to_hub()
    inv = await _run_inventory_push_to_hub()
    return {
        "message": "ok",
        "categorias": cat,
        "proveedores": prv,
        "inventario": inv,
    }


def _start_catalog_sync_job(
    job_id: str,
    *,
    direction: str,
    background_tasks: BackgroundTasks,
) -> str:
    if not settings.huey_catalog_sync_enabled:
        raise HTTPException(
            status_code=503,
            detail="Catalog sync jobs disabled (HUEY_CATALOG_SYNC_ENABLED=false)",
        )

    from sync.jobs.store import save_job

    save_job(job_id, {"job_id": job_id, "direction": direction, "status": "pending"})

    if settings.huey_enabled:
        if direction == "push":
            from workers.huey_tasks import schedule_catalog_push_job

            schedule_catalog_push_job(job_id)
            return "push job enqueued (Huey)"
        from workers.huey_tasks import schedule_catalog_pull_job

        schedule_catalog_pull_job(job_id)
        return "pull job enqueued (Huey)"

    if direction == "push":
        from workers.huey_tasks import run_catalog_push_job

        background_tasks.add_task(run_catalog_push_job, job_id)
        return (
            "push job started in-process; set HUEY_ENABLED=true and run "
            "huey_consumer for production-style retries"
        )
    from workers.huey_tasks import run_catalog_pull_job

    background_tasks.add_task(run_catalog_pull_job, job_id)
    return (
        "pull job started in-process; set HUEY_ENABLED=true and run "
        "huey_consumer for production-style retries"
    )


@router.post("/jobs/{job_id}/push/start", status_code=202)
async def start_catalog_push_job(
    job_id: str,
    background_tasks: BackgroundTasks,
    _: None = Depends(verify_bearer),
):
    message = _start_catalog_sync_job(
        job_id,
        direction="push",
        background_tasks=background_tasks,
    )
    return JSONResponse(
        status_code=202,
        content={"jobId": job_id, "status": "pending", "message": message},
    )


@router.post("/jobs/{job_id}/pull/start", status_code=202)
async def start_catalog_pull_job(
    job_id: str,
    background_tasks: BackgroundTasks,
    _: None = Depends(verify_bearer),
):
    message = _start_catalog_sync_job(
        job_id, direction="pull", background_tasks=background_tasks
    )
    return JSONResponse(
        status_code=202,
        content={"jobId": job_id, "status": "pending", "message": message},
    )


@router.post("/jobs/{job_id}/cancel", status_code=200)
async def cancel_catalog_sync_job(
    job_id: str,
    _: None = Depends(verify_bearer),
):
    """Parada cooperativa: el worker comprueba cancel_requested en export/apply."""
    from sync.jobs.cancel import request_local_cancel
    from sync.jobs.files import delete_job_file

    request_local_cancel(job_id)
    delete_job_file(job_id)
    delete_job_file(f"{job_id}-purchase")
    delete_job_file(f"{job_id}-sale")
    return {"jobId": job_id, "status": "cancelled", "message": "ok"}


@router.get("/jobs/{job_id}")
async def get_catalog_job(job_id: str, _: None = Depends(verify_bearer)):
    from sync.jobs.store import load_job

    local = load_job(job_id)
    if local:
        return local
    try:
        hub = HubClient()
        return await hub.get_sync_job(job_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/categorias")
async def sync_categorias(_: None = Depends(verify_bearer)):
    mysql = MySqlClient()
    if not mysql.is_configured():
        raise RuntimeError("Node MySQL not configured (set MYSQL_* in .env)")

    def fetch():
        conn = mysql.connect()
        try:
            cur = conn.cursor(dictionary=True)
            cur.execute(
                """
                SELECT ccate, ncate, pganancia, pdescu
                FROM catego
                ORDER BY ncate ASC
                """
            )
            return cur.fetchall() or []
        finally:
            conn.close()

    items = await anyio.to_thread.run_sync(fetch)
    return {"items": items, "message": "ok"}


@router.get("/status")
async def sync_status(_: None = Depends(verify_bearer)):
    store = get_sync_store()
    state = await store.get_state()
    return {
        "nodo_id": settings.nodo_id,
        "role": settings.nodo_role,
        "sync": "running" if settings.sync_worker_enabled else "disabled",
        **state,
    }


class OutboxDeleteBody(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=500)


def _parse_outbox_statuses(raw: str | None) -> list[str] | None:
    if not raw or not raw.strip():
        return None
    return [part.strip() for part in raw.split(",") if part.strip()]


@router.get("/outbox/status")
async def outbox_status(_: None = Depends(verify_bearer)):
    repo = get_outbox_repo()
    stats = await anyio.to_thread.run_sync(repo.stats)
    recent_pending = await anyio.to_thread.run_sync(lambda: repo.recent("pending", 20))
    recent_failed = await anyio.to_thread.run_sync(lambda: repo.recent("failed", 20))
    return {
        "nodo_id": settings.nodo_id,
        "db": settings.mysql_database,
        "outbox": {
            "stats": stats,
            "recent_pending": recent_pending,
            "recent_failed": recent_failed,
        },
    }


@router.get("/outbox")
async def outbox_list(
    _: None = Depends(verify_bearer),
    status: str | None = Query(
        None,
        description="Comma-separated: pending,processing,failed (default: all three)",
    ),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
):
    repo = get_outbox_repo()
    statuses = _parse_outbox_statuses(status)
    offset = (page - 1) * limit

    def _load() -> tuple[list[dict], int, dict[str, int]]:
        items, total = repo.list_queue(
            statuses=statuses, limit=limit, offset=offset
        )
        return items, total, repo.stats()

    items, total, stats = await anyio.to_thread.run_sync(_load)
    total_pages = max(1, (total + limit - 1) // limit) if total else 1
    return {
        "nodo_id": settings.nodo_id,
        "db": settings.mysql_database,
        "stats": stats,
        "items": items,
        "pagination": {
            "page": page,
            "limit": limit,
            "total": total,
            "total_pages": total_pages,
        },
    }


@router.post("/outbox/flush")
async def outbox_flush(
    _: None = Depends(verify_bearer),
    max_batches: int = Query(20, ge=1, le=100),
):
    from workers.huey_tasks import run_outbox_flush_once

    batches: list[dict] = []
    total_sent = 0
    total_ignored = 0
    total_failed = 0

    for _ in range(max_batches):
        try:
            result = await anyio.to_thread.run_sync(run_outbox_flush_once)
        except Exception as ex:
            raise HTTPException(
                status_code=502,
                detail=f"Outbox flush failed: {ex}",
            ) from ex
        batches.append(result)
        total_sent += int(result.get("sent") or 0)
        total_ignored += int(result.get("ignored") or 0)
        total_failed += int(result.get("failed") or 0)
        if result.get("message") == "no_pending":
            break

    repo = get_outbox_repo()
    stats = await anyio.to_thread.run_sync(repo.stats)
    return {
        "nodo_id": settings.nodo_id,
        "batches_run": len(batches),
        "sent": total_sent,
        "ignored": total_ignored,
        "failed": total_failed,
        "stats": stats,
        "batches": batches,
    }


@router.post("/outbox/delete")
async def outbox_delete(
    body: OutboxDeleteBody,
    _: None = Depends(verify_bearer),
):
    repo = get_outbox_repo()
    deleted = await anyio.to_thread.run_sync(
        lambda: repo.delete_by_ids(body.ids),
    )
    stats = await anyio.to_thread.run_sync(repo.stats)
    return {
        "nodo_id": settings.nodo_id,
        "requested": len(body.ids),
        "deleted": deleted,
        "stats": stats,
    }
