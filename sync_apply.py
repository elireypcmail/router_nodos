from __future__ import annotations

from typing import Any

from categoria_trace import trace, trace_exc
from db_mysql import MySqlClient
from sprv_store import delete_sprv, upsert_sprv
from sync_store import SyncEvent


class SyncApplier:
    def __init__(self, mysql: MySqlClient):
        self._mysql = mysql

    async def apply(self, event: SyncEvent) -> None:
        if not self._mysql.is_configured():
            raise RuntimeError("MySQL del nodo no configurado (MYSQL_* en .env)")

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

        raise RuntimeError(f"Entidad no soportada: {event.entity}")

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
            raise RuntimeError("payload.items debe ser una lista")

        trace("worker.apply.items", event_id=event.event_id, count=len(items))
        conn = self._mysql.connect()
        try:
            cur = conn.cursor()
            for item in items:
                if not isinstance(item, dict):
                    raise RuntimeError("cada item debe ser un objeto")
                ccate = str(item.get("ccate") or "").strip()
                ncate = str(item.get("ncate") or "").strip()
                if not ccate or not ncate:
                    raise RuntimeError("categoria requiere ccate y ncate")

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
            raise RuntimeError("payload.row debe ser objeto")

        cod_prv = str(row.get("cod_prv") or "").strip()
        if not cod_prv:
            raise RuntimeError("proveedor requiere cod_prv")

        conn = self._mysql.connect()
        try:
            cur = conn.cursor()
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
            raise RuntimeError("payload.row debe ser objeto")

        codigo = str(row.get("codigo") or "").strip()
        if not codigo:
            raise RuntimeError("inventario requiere codigo")

        conn = self._mysql.connect()
        try:
            cur = conn.cursor()
            if event.action == "delete":
                cur.execute("DELETE FROM sinv WHERE codigo = %s", (codigo,))
                conn.commit()
                return

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
                    row.get("descrip"),
                    row.get("barra"),
                    row.get("existencia"),
                    row.get("precio1"),
                    row.get("ccate"),
                    row.get("cod_prv"),
                    row.get("activo"),
                ),
            )
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
            raise RuntimeError("payload.row debe ser objeto")
        if pk is not None and not isinstance(pk, dict):
            raise RuntimeError("payload.pk debe ser objeto")

        conn = self._mysql.connect()
        try:
            cur = conn.cursor()
            if event.action == "delete":
                where_pk = pk or {}
                if table == "ventas":
                    numero = str(where_pk.get("numero") or row.get("numero") or "").strip()
                    if not numero:
                        raise RuntimeError("ventas delete requiere numero")
                    cur.execute("DELETE FROM ventas WHERE numero = %s", (numero,))
                elif table == "ventasd":
                    numero = str(where_pk.get("numero") or row.get("numero") or "").strip()
                    codigo = str(where_pk.get("codigo") or row.get("codigo") or "").strip()
                    indice_det = where_pk.get("indice_det")
                    if indice_det is None:
                        indice_det = row.get("indice_det")
                    if not numero or not codigo or indice_det is None:
                        raise RuntimeError("ventasd delete requiere numero, codigo, indice_det")
                    cur.execute(
                        "DELETE FROM ventasd WHERE numero=%s AND codigo=%s AND indice_det=%s",
                        (numero, codigo, int(indice_det)),
                    )
                elif table in {"kardex", "kardexd"}:
                    indice = where_pk.get("indice")
                    if indice is None:
                        indice = row.get("indice")
                    if indice is None:
                        raise RuntimeError("kardex/kardexd delete requiere indice")
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
                        raise RuntimeError("comprasdbf delete requiere contador,numdoc,codigo,fecha")
                    cur.execute(
                        "DELETE FROM comprasdbf WHERE contador=%s AND numdoc=%s AND codigo=%s AND fecha=%s",
                        (int(contador), numdoc, codigo, fecha),
                    )
                else:
                    raise RuntimeError(f"delete no soportado para {table}")

                conn.commit()
                return

            cols = list(row.keys())
            if not cols:
                raise RuntimeError("row vacío")
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
