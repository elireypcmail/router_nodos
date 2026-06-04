from __future__ import annotations

from typing import Any

from core.categoria_trace import trace, trace_exc
from db.mysql import MySqlClient
from db.outbox_suppress import hub_origin_write
from db.sinv_store import delete_sinv, prepare_sinv_upsert, upsert_sinv
from db.sprv_store import delete_sprv, upsert_sprv
from sync.store import SyncEvent


class SyncApplier:
    def __init__(self, mysql: MySqlClient):
        self._mysql = mysql

    async def apply(self, event: SyncEvent) -> None:
        if not self._mysql.is_configured():
            raise RuntimeError("Node MySQL not configured (set MYSQL_* in .env)")

        entity = (event.entity or "").strip().lower()

        if entity in {"categorias", "categoria", "inventory_category", "catego"}:
            await self._apply_categorias(event)
            return

        if entity in {"proveedores", "proveedor", "provider", "sprv"}:
            await self._apply_proveedor(event)
            return

        if entity in {"inventario", "inventory", "sinv"}:
            await self._apply_inventario(event)
            return

        if entity in {"ventas", "ventasd", "kardex", "kardexd", "comprasdbf"}:
            await self._apply_transaccional(event, table=entity)
            return

        raise RuntimeError(f"Unsupported entity: {event.entity}")

    async def _apply_categorias(self, event: SyncEvent) -> None:
        trace(
            "worker.apply.start",
            event_id=event.event_id,
            action=event.action,
            sequence=event.sequence,
        )
        payload: dict[str, Any] = event.payload or {}

        items = payload.get("items")
        if items is None:
            item = payload.get("row")
            if item is None:
                item = payload
            items = [item]

        if not isinstance(items, list):
            raise RuntimeError("payload.items must be a list")

        trace("worker.apply.items", event_id=event.event_id, count=len(items))
        conn = self._mysql.connect()
        try:
            cur = conn.cursor()
            with hub_origin_write(cur):
                for item in items:
                    if not isinstance(item, dict):
                        raise RuntimeError("each item must be an object")
                    ccate = str(item.get("ccate") or "").strip()
                    ncate = str(item.get("ncate") or "").strip()
                    if not ccate or not ncate:
                        raise RuntimeError("category requires ccate and ncate")

                    trace("worker.apply.row", event_id=event.event_id, ccate=ccate, action=event.action)
                    if event.action == "upsert":
                        cur.execute(
                            """
                            INSERT INTO catego (ccate, ncate)
                            VALUES (%s, %s)
                            ON DUPLICATE KEY UPDATE ncate = VALUES(ncate)
                            """,
                            (ccate, ncate),
                        )
                    elif event.action == "delete":
                        cur.execute("DELETE FROM catego WHERE ccate = %s", (ccate,))

            conn.commit()
            trace("worker.apply.done", event_id=event.event_id)
        except Exception as exc:
            conn.rollback()
            trace_exc("worker.apply.failed", exc, event_id=event.event_id)
            raise
        finally:
            conn.close()

    async def _apply_proveedor(self, event: SyncEvent) -> None:
        payload: dict[str, Any] = event.payload or {}
        row = payload.get("row")
        if row is None:
            row = payload
        if not isinstance(row, dict):
            raise RuntimeError("payload.row must be an object")

        cod_prv = str(row.get("cod_prv") or "").strip()
        if not cod_prv:
            raise RuntimeError("provider row requires cod_prv")

        conn = self._mysql.connect()
        try:
            cur = conn.cursor()
            with hub_origin_write(cur):
                if event.action == "delete":
                    delete_sprv(cur, cod_prv)
                else:
                    upsert_sprv(cur, row)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    async def _apply_inventario(self, event: SyncEvent) -> None:
        payload: dict[str, Any] = event.payload or {}
        row = payload.get("row")
        if row is None:
            row = payload
        if not isinstance(row, dict):
            raise RuntimeError("payload.row must be an object")

        codigo = str(row.get("codigo") or "").strip()
        if not codigo:
            raise RuntimeError("inventory row requires codigo")

        conn = self._mysql.connect()
        try:
            cur = conn.cursor()
            with hub_origin_write(cur):
                if event.action == "delete":
                    delete_sinv(cur, codigo)
                else:
                    upsert_sinv(cur, prepare_sinv_upsert(row))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    async def _apply_transaccional(self, event: SyncEvent, table: str) -> None:
        payload: dict[str, Any] = event.payload or {}
        row = payload.get("row")
        pk = payload.get("pk")
        if not isinstance(row, dict):
            raise RuntimeError("payload.row must be an object")
        if pk is not None and not isinstance(pk, dict):
            raise RuntimeError("payload.pk must be an object")

        conn = self._mysql.connect()
        try:
            cur = conn.cursor()
            if event.action == "delete":
                where_pk = pk or {}
                if table == "ventas":
                    numero = str(where_pk.get("numero") or row.get("numero") or "").strip()
                    if not numero:
                        raise RuntimeError("ventas delete requires numero")
                    cur.execute("DELETE FROM ventas WHERE numero = %s", (numero,))
                elif table == "ventasd":
                    numero = str(where_pk.get("numero") or row.get("numero") or "").strip()
                    codigo = str(where_pk.get("codigo") or row.get("codigo") or "").strip()
                    indice_det = where_pk.get("indice_det")
                    if indice_det is None:
                        indice_det = row.get("indice_det")
                    if not numero or not codigo or indice_det is None:
                        raise RuntimeError("ventasd delete requires numero, codigo, indice_det")
                    cur.execute(
                        "DELETE FROM ventasd WHERE numero=%s AND codigo=%s AND indice_det=%s",
                        (numero, codigo, int(indice_det)),
                    )
                elif table in {"kardex", "kardexd"}:
                    indice = where_pk.get("indice")
                    if indice is None:
                        indice = row.get("indice")
                    if indice is None:
                        raise RuntimeError("kardex/kardexd delete requires indice")
                    cur.execute(f"DELETE FROM {table} WHERE indice = %s", (int(indice),))
                elif table == "comprasdbf":
                    contador = where_pk.get("contador")
                    numdoc = str(where_pk.get("numdoc") or "").strip()
                    codigo = str(where_pk.get("codigo") or "").strip()
                    fecha = where_pk.get("fecha")
                    if contador is None:
                        contador = row.get("contador")
                    if not numdoc:
                        numdoc = str(row.get("numdoc") or "").strip()
                    if not codigo:
                        codigo = str(row.get("codigo") or "").strip()
                    if fecha is None:
                        fecha = row.get("fecha")
                    if contador is None or not numdoc or not codigo or fecha is None:
                        raise RuntimeError("comprasdbf delete requires contador,numdoc,codigo,fecha")
                    cur.execute(
                        "DELETE FROM comprasdbf WHERE contador=%s AND numdoc=%s AND codigo=%s AND fecha=%s",
                        (int(contador), numdoc, codigo, fecha),
                    )
                else:
                    raise RuntimeError(f"delete not supported for {table}")

                conn.commit()
                return

            cols = list(row.keys())
            if not cols:
                raise RuntimeError("empty row")
            placeholders = ", ".join(["%s"] * len(cols))
            col_list = ", ".join(cols)
            update_list = ", ".join([f"{c}=VALUES({c})" for c in cols])
            sql = f"INSERT INTO {table} ({col_list}) VALUES ({placeholders}) ON DUPLICATE KEY UPDATE {update_list}"
            cur.execute(sql, tuple(row[c] for c in cols))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
