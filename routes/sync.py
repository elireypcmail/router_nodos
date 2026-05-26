from fastapi import APIRouter, Depends, HTTPException, Query, Request

import anyio
from pydantic import BaseModel, Field

from config import settings
from db_mysql import MySqlClient
from hub_client import HubClient
from middleware.auth import verify_bearer
from sync_models import SyncApplyRequest
from sync_store import SyncEvent

router = APIRouter(prefix="/api/sync", tags=["sync"])


class SyncEventBody(BaseModel):
    entity_type: str = Field(..., description="Ej. inventory_category, provider")
    payload: dict = Field(default_factory=dict)


def get_sync_store():
    from main import sync_store

    if not sync_store:
        raise RuntimeError("sync_store no inicializado")
    return sync_store


def get_outbox_repo():
    from main import outbox_repo

    if not outbox_repo:
        raise RuntimeError("outbox_repo no inicializado")
    return outbox_repo


@router.post("/apply")
async def sync_apply(
    body: SyncApplyRequest,
    _: None = Depends(verify_bearer),
):
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
    mysql = MySqlClient()
    if not mysql.is_configured():
        raise RuntimeError("MySQL del nodo no configurado (MYSQL_* en .env)")

    entity = body.entity_type.strip().lower()
    payload = body.payload or {}

    if entity in {"inventory_category", "categorias", "categoria"}:
        ccate = str(payload.get("ccate") or "").strip()
        ncate = str(payload.get("ncate") or "").strip()
        pganancia = payload.get("pganancia")
        pdescu = payload.get("pdescu")
        if not ccate or not ncate:
            raise HTTPException(status_code=422, detail="categoria requiere ccate y ncate")

        def upsert():
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
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

        await anyio.to_thread.run_sync(upsert)
        return {"received": True, "entity_type": body.entity_type, "message": "ok"}

    if entity in {"proveedores", "proveedor", "provider", "sprv"}:
        action = str(payload.get("action") or "upsert").strip().lower()
        row = payload.get("row")
        if row is None:
            row = payload
        if not isinstance(row, dict):
            raise HTTPException(status_code=422, detail="payload.row debe ser objeto")

        def apply_row():
            conn = mysql.connect()
            try:
                cur = conn.cursor()
                cod_prv = str(row.get("cod_prv") or "").strip()
                if not cod_prv:
                    raise RuntimeError("proveedor requiere cod_prv")

                if action == "delete":
                    cur.execute("DELETE FROM sprv WHERE cod_prv = %s", (cod_prv,))
                    conn.commit()
                    return

                rif_prv = str(row.get("rif_prv") or "").strip()
                nom_prv = str(row.get("nom_prv") or "").strip()
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
                      dir1_prv = %s,
                      dir2_prv = %s,
                      dir3_prv = %s,
                      tel_prv = %s,
                      email1_prv = %s,
                      email2_prv = %s,
                      rep_prv = %s,
                      especial = %s,
                      numcuenta = %s
                    WHERE cod_prv = %s
                    """,
                    (
                        row.get("nom_prv"),
                        row.get("rif_prv"),
                        row.get("dir1_prv"),
                        row.get("dir2_prv"),
                        row.get("dir3_prv"),
                        row.get("tel_prv"),
                        row.get("email1_prv"),
                        row.get("email2_prv"),
                        row.get("rep_prv"),
                        row.get("especial"),
                        row.get("numcuenta"),
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
                          dir1_prv,
                          dir2_prv,
                          dir3_prv,
                          tel_prv,
                          email1_prv,
                          email2_prv,
                          rep_prv,
                          especial,
                          numcuenta
                        )
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                        """,
                        (
                            cod_prv,
                            row.get("nom_prv"),
                            row.get("rif_prv"),
                            row.get("dir1_prv"),
                            row.get("dir2_prv"),
                            row.get("dir3_prv"),
                            row.get("tel_prv"),
                            row.get("email1_prv"),
                            row.get("email2_prv"),
                            row.get("rep_prv"),
                            row.get("especial"),
                            row.get("numcuenta"),
                        ),
                    )
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
            raise HTTPException(status_code=422, detail="payload.row debe ser objeto")

        def apply_row():
            conn = mysql.connect()
            try:
                cur = conn.cursor()
                codigo = str(row.get("codigo") or "").strip()
                if not codigo:
                    raise RuntimeError("inventario requiere codigo")

                if action == "delete":
                    cur.execute("DELETE FROM sinv WHERE codigo = %s", (codigo,))
                    conn.commit()
                    return

                cur.execute(
                    """
                    INSERT INTO sinv (
                      codigo, descrip, ccate, cod_prv, precio1, pg1, barra, referencia,
                      componente, stockmin, stockmax, recipe, cfrio, activo, existencia
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                      descrip = VALUES(descrip),
                      ccate = VALUES(ccate),
                      cod_prv = VALUES(cod_prv),
                      precio1 = VALUES(precio1),
                      pg1 = VALUES(pg1),
                      barra = VALUES(barra),
                      referencia = VALUES(referencia),
                      componente = VALUES(componente),
                      stockmin = VALUES(stockmin),
                      stockmax = VALUES(stockmax),
                      recipe = VALUES(recipe),
                      cfrio = VALUES(cfrio),
                      activo = VALUES(activo),
                      existencia = VALUES(existencia)
                    """,
                    (
                        codigo,
                        row.get("descrip"),
                        row.get("ccate"),
                        row.get("cod_prv"),
                        row.get("precio1"),
                        row.get("pg1"),
                        row.get("barra"),
                        row.get("referencia"),
                        row.get("componente"),
                        row.get("stockmin"),
                        row.get("stockmax"),
                        row.get("recipe"),
                        row.get("cfrio"),
                        row.get("activo"),
                        row.get("existencia"),
                    ),
                )
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
            detail="Transaccional (compras/ventas/kardex) no se aplica por push; debe entrar por pull (/orchestration/sync/events)",
        )

    raise HTTPException(status_code=400, detail=f"entity_type no soportado: {body.entity_type}")


@router.post("/categorias")
async def sync_categorias_legacy(request: Request, _: None = Depends(verify_bearer)):
    """Compatibilidad guía: /api/sync/categorias delega a /api/sync/events."""
    payload = await request.json()
    return await sync_events(SyncEventBody(entity_type="inventory_category", payload=payload), _)


@router.post("/categorias/pull")
async def sync_categorias_pull(
    page_size: int = Query(100, ge=1, le=500, description="Tamaño de página al hub"),
    _: None = Depends(verify_bearer),
):
    """Contrato guía: el hub le pide al nodo que ejecute un pull paginado al hub."""
    mysql = MySqlClient()
    if not mysql.is_configured():
        raise RuntimeError("MySQL del nodo no configurado (MYSQL_* en .env)")

    hub = HubClient()

    async def fetch_all():
        from pull_worker import pull_all_categories

        return await pull_all_categories(hub, page_size=page_size)

    items = await fetch_all()
    if not items:
        return {"pulled": 0, "page_size": page_size, "message": "ok"}

    def bulk_upsert():
        conn = mysql.connect()
        try:
            cur = conn.cursor()
            for it in items:
                if not isinstance(it, dict):
                    continue
                ccate = str(it.get("ccate") or "").strip()
                ncate = str(it.get("ncate") or "").strip()
                if not ccate or not ncate:
                    continue
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
                        it.get("pganancia"),
                        it.get("pdescu"),
                    ),
                )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    await anyio.to_thread.run_sync(bulk_upsert)
    return {"pulled": len(items), "page_size": page_size, "message": "ok"}


@router.get("/categorias")
async def sync_categorias(_: None = Depends(verify_bearer)):
    mysql = MySqlClient()
    if not mysql.is_configured():
        raise RuntimeError("MySQL del nodo no configurado (MYSQL_* en .env)")

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
