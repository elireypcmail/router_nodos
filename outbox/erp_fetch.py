"""Lecturas ERP para enriquecer eventos outbox antes de enviar al router."""

from __future__ import annotations

from typing import Any

from core.json_util import json_safe
from db.lotes_store import fetch_lotes_groups, lotes_where
from db.mysql import MySqlClient


def _strip(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _fetch_one(cur, sql: str, params: tuple) -> dict[str, Any] | None:
    cur.execute(sql, params)
    row = cur.fetchone()
    if not row:
        return None
    return json_safe(row)


def parse_sale_keys(
    row: dict[str, Any],
    pk: dict[str, Any] | None,
) -> tuple[str, str, object, str]:
    pk = pk or {}
    numero = _strip(row.get("numero") or pk.get("numero"))
    codigo = _strip(row.get("codigo") or pk.get("codigo"))
    contador = row.get("contador")
    if contador is None:
        contador = pk.get("contador")
    ccaja = _strip(row.get("ccaja") or pk.get("ccaja"))
    return numero, codigo, contador, ccaja


def fetch_diariovi_line(
    mysql: MySqlClient,
    *,
    numero: str,
    codigo: str,
    contador: object,
    ccaja: str,
) -> dict[str, Any] | None:
    c = _strip(codigo)
    if not c:
        return None
    conn = mysql.connect()
    try:
        cur = conn.cursor(dictionary=True)
        n = _strip(numero)
        if n and contador is not None:
            row = _fetch_one(
                cur,
                """
                SELECT * FROM diariovi
                WHERE TRIM(numero)=%s AND TRIM(codigo)=%s AND contador=%s
                LIMIT 1
                """,
                (n, c, contador),
            )
            if row:
                return row
        if n:
            row = _fetch_one(
                cur,
                """
                SELECT * FROM diariovi
                WHERE TRIM(numero)=%s AND TRIM(codigo)=%s
                ORDER BY contador DESC
                LIMIT 1
                """,
                (n, c),
            )
            if row:
                return row
        if contador is not None:
            return _fetch_one(
                cur,
                """
                SELECT * FROM diariovi
                WHERE TRIM(codigo)=%s AND contador=%s
                ORDER BY fecha DESC, contador DESC
                LIMIT 1
                """,
                (c, contador),
            )
        return None
    finally:
        conn.close()


def fetch_diariov_by_ccaja(
    mysql: MySqlClient,
    ccaja: str,
) -> dict[str, Any] | None:
    """Cabecera de preventa/venta por ccaja (para leer nordene público)."""
    key = _strip(ccaja)
    if not key:
        return None
    conn = mysql.connect()
    try:
        cur = conn.cursor(dictionary=True)
        return _fetch_one(
            cur,
            """
            SELECT nordene, ccaja, numero, cod_cli, fecha
            FROM diariov
            WHERE TRIM(ccaja)=%s
            ORDER BY fecha DESC
            LIMIT 1
            """,
            (key,),
        )
    finally:
        conn.close()


def fetch_detallepr_row(mysql: MySqlClient, codigo: str) -> dict[str, Any] | None:
    c = _strip(codigo)
    if not c:
        return None
    conn = mysql.connect()
    try:
        cur = conn.cursor(dictionary=True)
        return _fetch_one(
            cur,
            "SELECT * FROM detallepr WHERE TRIM(codigo)=%s LIMIT 1",
            (c,),
        )
    finally:
        conn.close()


def fetch_scom_line(
    mysql: MySqlClient,
    *,
    numero: str,
    codigo: str,
) -> dict[str, Any] | None:
    n = _strip(numero)
    c = _strip(codigo)
    if not c:
        return None
    conn = mysql.connect()
    try:
        cur = conn.cursor(dictionary=True)
        if n:
            row = _fetch_one(
                cur,
                """
                SELECT * FROM scom
                WHERE TRIM(numero)=%s AND TRIM(codigo)=%s
                ORDER BY indice DESC
                LIMIT 1
                """,
                (n, c),
            )
            if row:
                return row
        return None
    finally:
        conn.close()


def fetch_sinv_row(mysql: MySqlClient, codigo: str) -> dict[str, Any] | None:
    c = _strip(codigo)
    if not c:
        return None
    conn = mysql.connect()
    try:
        cur = conn.cursor(dictionary=True)
        return _fetch_one(
            cur,
            "SELECT * FROM sinv WHERE TRIM(codigo)=%s LIMIT 1",
            (c,),
        )
    finally:
        conn.close()


def fetch_detalle_lotes(
    mysql: MySqlClient,
    codigo: str,
) -> list[dict[str, Any]]:
    c = _strip(codigo)
    if not c:
        return []
    conn = mysql.connect()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            """
            SELECT *
            FROM detalle
            WHERE TRIM(codigo)=%s AND disponible='S' AND existencia > 0
            ORDER BY
              CASE
                WHEN vence IS NULL OR DATE(vence) IN ('1970-01-01', '0000-00-00') THEN 1
                ELSE 0
              END,
              vence ASC,
              indice ASC
            """,
            (c,),
        )
        return [json_safe(r) for r in (cur.fetchall() or [])]
    finally:
        conn.close()


def fetch_lotes_aggregated(
    mysql: MySqlClient,
    codigo: str,
) -> tuple[list[dict[str, Any]], float]:
    c = _strip(codigo)
    if not c:
        return [], 0.0
    where_sql, params = lotes_where(c)
    conn = mysql.connect()
    try:
        cur = conn.cursor(dictionary=True)
        rows = fetch_lotes_groups(cur, where_sql, params)
    finally:
        conn.close()
    lotes = [json_safe(row) for row in rows]
    existencia = sum(float(row.get("existencia") or 0) for row in lotes)
    return lotes, existencia


def fetch_sprv_row(mysql: MySqlClient, cod_prv: str) -> dict[str, Any] | None:
    code = _strip(cod_prv)
    if not code:
        return None
    conn = mysql.connect()
    try:
        cur = conn.cursor(dictionary=True)
        return _fetch_one(
            cur,
            "SELECT * FROM sprv WHERE TRIM(cod_prv)=%s LIMIT 1",
            (code,),
        )
    finally:
        conn.close()


def fetch_kardex_obs(
    mysql: MySqlClient,
    indice: object,
) -> dict[str, Any] | None:
    """kobs / hora / fecha desde kardex por índice (ventas/ajustes sin kobs en outbox)."""
    if indice is None or indice == "":
        return None
    try:
        idx = int(indice)
    except (TypeError, ValueError):
        return None
    conn = mysql.connect()
    try:
        cur = conn.cursor(dictionary=True)
        return _fetch_one(
            cur,
            """
            SELECT kobs, hora, fecha, indice
            FROM kardex
            WHERE indice=%s
            LIMIT 1
            """,
            (idx,),
        )
    finally:
        conn.close()
