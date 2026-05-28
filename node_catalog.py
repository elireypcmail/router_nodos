"""Lee sinv + catego + sprv locales para enviar al hub en ingest (node_catalog)."""

from __future__ import annotations

from db_mysql import MySqlClient
from json_util import json_safe


def _pick_str(value: object | None) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _get_sinv(codigo: str) -> dict | None:
    code = _pick_str(codigo)
    if not code:
        return None

    mysql = MySqlClient()
    if not mysql.is_configured():
        return None

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
              precio1,
              pg1,
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
              costoant
            FROM sinv
            WHERE codigo = %s
            LIMIT 1
            """,
            (code,),
        )
        row = cur.fetchone()
        return json_safe(dict(row)) if row else None
    finally:
        conn.close()


def _get_catego(ccate: str) -> dict | None:
    code = _pick_str(ccate)
    if not code:
        return None

    mysql = MySqlClient()
    if not mysql.is_configured():
        return None

    conn = mysql.connect()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            """
            SELECT ccate, ncate, pganancia, pdescu
            FROM catego
            WHERE ccate = %s
            LIMIT 1
            """,
            (code,),
        )
        row = cur.fetchone()
        return json_safe(dict(row)) if row else None
    finally:
        conn.close()


def _get_sprv(cod_prv: str) -> dict | None:
    code = _pick_str(cod_prv)
    if not code:
        return None

    mysql = MySqlClient()
    if not mysql.is_configured():
        return None

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
            (code,),
        )
        row = cur.fetchone()
        return json_safe(dict(row)) if row else None
    finally:
        conn.close()


def load_node_catalog(codigo: str) -> dict | None:
    """
    Snapshot para el hub: producto (sinv) y, si aplica, categoría y proveedor.
    None si el código no existe en sinv.
    """
    product = _get_sinv(codigo)
    if not product:
        return None

    ccate = _pick_str(product.get("ccate"))
    cod_prv = _pick_str(product.get("cod_prv"))

    category = _get_catego(ccate) if ccate else None
    provider = _get_sprv(cod_prv) if cod_prv else None

    return {
        "product": product,
        "category": category,
        "provider": provider,
    }
